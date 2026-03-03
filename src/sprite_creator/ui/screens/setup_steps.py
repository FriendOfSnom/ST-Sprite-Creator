"""
Setup wizard steps (Steps 1-3).

These steps collect initial configuration data before generation begins:
1. Source Selection - Image upload, text prompt, or fusion
2. Character Info - Name, voice, archetype, concept (includes crop for image mode)
3. Generation Options - Outfit and expression selection
"""

import random
import threading
import tkinter as tk
from io import BytesIO
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageTk

from ...config import (
    ALL_OUTFIT_KEYS,
    OUTFIT_KEYS,
    EXPRESSIONS_SEQUENCE,
    NAMES_CSV_PATH,
    GENDER_ARCHETYPES,
    BG_COLOR,
    BG_SECONDARY,
    CARD_BG,
    TEXT_COLOR,
    TEXT_SECONDARY,
    ACCENT_COLOR,
    ACCENT_HOVER,
    BORDER_COLOR,
    DANGER_COLOR,
    ERROR_TEXT,
    WARNING_TEXT,
    OVERLAY_BG,
    PAGE_TITLE_FONT,
    SECTION_FONT,
    BODY_FONT,
    SMALL_FONT,
    SMALL_FONT_BOLD,
    get_backup_dir,
    load_saved_outfits,
    save_outfit,
    delete_saved_outfit,
)
from ..tk_common import (
    create_primary_button,
    create_secondary_button,
    create_option_card,
    OptionCard,
    create_toggle_chip,
    create_segmented_control,
    ToggleChip,
    FilledChip,
    get_primary_screen,
)
from ..dialogs import load_name_pool, pick_random_name
from .base import WizardStep, WizardState
from ...api.exceptions import GeminiSafetyError
from ...logging_utils import log_info, log_error, log_generation_start, log_generation_complete


# Fusion image slot dimensions (same as original FusionStep per user request)
FUSION_SLOT_WIDTH = 420
FUSION_SLOT_HEIGHT = 520


# =============================================================================
# Step 1: Source Selection
# =============================================================================

class SourceStep(WizardStep):
    """Step 1: Choose between image upload, text prompt, or fusion."""

    STEP_ID = "source"
    STEP_TITLE = "Source"
    STEP_NUMBER = 1
    STEP_TIP = (
        "Choose how to create your character: upload an existing image, "
        "describe one with a text prompt, or fuse two characters together."
    )
    STEP_HELP = """How to Create Your Character

This step determines how your character will be created.

FROM AN IMAGE
Click the "From an Image" card, then click "Browse for Image..." to select your source file.

Supported formats: PNG, JPG, JPEG, WEBP

For best results, your image should have:
- A standing pose (full body or waist-up)
- A simple or solid background (the AI will normalize it)
- Anime/illustration style artwork
- Clear, unobstructed view of the character
- Resolution of at least 512x512 pixels

The AI will normalize your image (sharpen, add solid background) and then generate outfit variations and expressions while preserving the character's appearance.

FROM A TEXT PROMPT
Click the "From a Text Prompt" card to describe a character from scratch.

You'll enter details in the next step, including:
- Physical appearance (hair color, eye color, body type)
- Clothing style and colors
- Personality traits that affect expression
- Any distinctive features

The AI will design the character based on your description.

FROM FUSION
Click the "From Fusion" card to merge two existing character images into a new unique character.

Select two character images (left and right), fill in the character settings (including hair length for girl voices), then click FUSION! to generate a merged character. Great for creating children of two characters or combining character traits.

Tips for best fusion results:
- Use images with similar art styles
- Characters with clear, visible features work best
- Front-facing poses produce more predictable results

WHICH SHOULD I CHOOSE?
- Use "From Image" if you have existing artwork or want to match a specific look
- Use "Text Prompt" to create something entirely new
- Use "Fusion" to combine two existing characters into one

After selecting, click Next to continue."""

    def __init__(self, wizard, state: WizardState):
        super().__init__(wizard, state)
        self._source_cards: List[OptionCard] = []
        self._image_preview_label: Optional[tk.Label] = None
        self._image_preview_frame: Optional[tk.Frame] = None
        self._preview_image_display: Optional[tk.Label] = None
        self._tk_preview_img: Optional[ImageTk.PhotoImage] = None

        # Fusion UI elements
        self._fusion_frame: Optional[tk.Frame] = None
        self._fusion_left_label: Optional[tk.Label] = None
        self._fusion_right_label: Optional[tk.Label] = None
        self._fusion_result_label: Optional[tk.Label] = None
        self._fusion_result_slot: Optional[tk.Frame] = None  # For localized loading
        self._fusion_loading_overlay: Optional[tk.Frame] = None
        self._fusion_left_tk_img: Optional[ImageTk.PhotoImage] = None
        self._fusion_right_tk_img: Optional[ImageTk.PhotoImage] = None
        self._fusion_result_tk_img: Optional[ImageTk.PhotoImage] = None
        self._fusion_btn: Optional[tk.Button] = None
        self._fusion_status_label: Optional[tk.Label] = None
        self._is_fusing: bool = False

        # Fusion settings
        self._fusion_voice_var: Optional[tk.StringVar] = None
        self._fusion_name_var: Optional[tk.StringVar] = None
        self._fusion_arch_var: Optional[tk.StringVar] = None
        self._fusion_arch_menu: Optional[tk.OptionMenu] = None
        self._fusion_hair_var: Optional[tk.StringVar] = None
        self._fusion_hair_frame: Optional[tk.Frame] = None
        self._fusion_hair_menu: Optional[tk.OptionMenu] = None
        self._fusion_voice_indicator: Optional[tk.Label] = None
        self._fusion_name_entry: Optional[tk.Entry] = None

        # Name pools for fusion
        self._girl_names, self._boy_names = load_name_pool(NAMES_CSV_PATH)

    def build_ui(self, parent: tk.Frame) -> None:
        parent.configure(bg=BG_COLOR)

        # Title
        tk.Label(
            parent,
            text="How would you like to create this character?",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=PAGE_TITLE_FONT,
        ).pack(pady=(0, 8))

        self._build_tip_bar(parent)

        # Cards container
        cards_frame = tk.Frame(parent, bg=BG_COLOR)
        cards_frame.pack()

        # Image card
        image_card = create_option_card(
            cards_frame,
            "From an Image",
            "Upload an existing character image.\nAI will create variations while\nmaintaining their appearance.",
            selected=True,
            on_click=lambda c: self._select_source_card(c, "image"),
            width=220,
            height=120,
        )
        image_card.pack(side="left", padx=8)
        self._source_cards.append(image_card)

        # Prompt card
        prompt_card = create_option_card(
            cards_frame,
            "From a Text Prompt",
            "Describe your character and\nlet AI design them from scratch.",
            selected=False,
            on_click=lambda c: self._select_source_card(c, "prompt"),
            width=220,
            height=120,
        )
        prompt_card.pack(side="left", padx=8)
        self._source_cards.append(prompt_card)

        # Fusion card
        fusion_card = create_option_card(
            cards_frame,
            "From Fusion",
            "Merge two existing characters\ninto a new unique character.",
            selected=False,
            on_click=lambda c: self._select_source_card(c, "fusion"),
            width=220,
            height=120,
        )
        fusion_card.pack(side="left", padx=8)
        self._source_cards.append(fusion_card)

        # Selected image preview (for image mode)
        self._image_preview_frame = tk.Frame(parent, bg=BG_COLOR)
        self._image_preview_frame.pack(pady=(16, 0))

        self._image_preview_label = tk.Label(
            self._image_preview_frame,
            text="No image selected",
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        )
        self._image_preview_label.pack()

        browse_btn = create_secondary_button(
            self._image_preview_frame,
            "Browse for Image...",
            self._browse_image,
            width=18,
        )
        browse_btn.pack(pady=(8, 0))

        # NSFW content warning
        tk.Label(
            self._image_preview_frame,
            text="Gemini cannot process nudity or minimal clothing\n"
                 "(underwear, swimsuits). Use a clothed character image.",
            bg=BG_COLOR,
            fg=WARNING_TEXT,
            font=SMALL_FONT,
            justify="center",
        ).pack(pady=(8, 0))

        self._preview_image_display = tk.Label(
            self._image_preview_frame,
            bg=BG_COLOR,
        )
        self._preview_image_display.pack(pady=(12, 0))

        # Fusion panel (hidden by default)
        self._fusion_frame = tk.Frame(parent, bg=BG_COLOR)
        self._build_fusion_panel(self._fusion_frame)

    def _build_fusion_panel(self, parent: tk.Frame) -> None:
        """Build the fusion UI panel."""
        # Settings row at top
        settings_card = tk.Frame(parent, bg=CARD_BG, padx=20, pady=12)
        settings_card.pack(fill="x", padx=20, pady=(0, 12))

        tk.Label(
            settings_card,
            text="Configure the new character",
            bg=CARD_BG,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        ).pack(pady=(0, 8))

        row_frame = tk.Frame(settings_card, bg=CARD_BG)
        row_frame.pack()

        # Voice selection
        voice_frame = tk.Frame(row_frame, bg=CARD_BG)
        voice_frame.pack(side="left", padx=(0, 20))

        tk.Label(voice_frame, text="Voice:", bg=CARD_BG, fg=TEXT_COLOR, font=BODY_FONT).pack(side="left", padx=(0, 6))

        self._fusion_voice_var = tk.StringVar(value="")

        girl_btn = create_secondary_button(voice_frame, "Girl", lambda: self._set_fusion_voice("girl"), width=6)
        girl_btn.pack(side="left", padx=(0, 4))

        boy_btn = create_secondary_button(voice_frame, "Boy", lambda: self._set_fusion_voice("boy"), width=6)
        boy_btn.pack(side="left")

        self._fusion_voice_indicator = tk.Label(voice_frame, text="", bg=CARD_BG, fg=ACCENT_COLOR, font=SMALL_FONT)
        self._fusion_voice_indicator.pack(side="left", padx=(6, 0))

        # Name entry
        name_frame = tk.Frame(row_frame, bg=CARD_BG)
        name_frame.pack(side="left", padx=(0, 20))

        tk.Label(name_frame, text="Name:", bg=CARD_BG, fg=TEXT_COLOR, font=BODY_FONT).pack(side="left", padx=(0, 6))

        self._fusion_name_var = tk.StringVar(value="")
        self._fusion_name_entry = tk.Entry(
            name_frame, textvariable=self._fusion_name_var, font=BODY_FONT, width=14,
            bg="#1E1E1E", fg=TEXT_COLOR, insertbackground=TEXT_COLOR
        )
        self._fusion_name_entry.pack(side="left")

        # Archetype selection
        arch_frame = tk.Frame(row_frame, bg=CARD_BG)
        arch_frame.pack(side="left")

        tk.Label(arch_frame, text="Archetype:", bg=CARD_BG, fg=TEXT_COLOR, font=BODY_FONT).pack(side="left", padx=(0, 6))

        self._fusion_arch_var = tk.StringVar(value="")
        self._fusion_arch_menu = tk.OptionMenu(arch_frame, self._fusion_arch_var, "")
        self._fusion_arch_menu.configure(width=12, bg="#1E1E1E", fg=TEXT_COLOR)
        self._fusion_arch_menu.pack(side="left")

        # Hair length selection (girl voice only) - inline with other settings
        HAIR_LENGTHS = ["Super Short", "Short", "Medium", "Long", "Super Long"]

        self._fusion_hair_frame = tk.Frame(row_frame, bg=CARD_BG)
        # Don't pack yet - visibility controlled by _update_fusion_hair_visibility

        tk.Label(
            self._fusion_hair_frame,
            text="Hair Length:",
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=BODY_FONT,
        ).pack(side="left", padx=(0, 6))

        self._fusion_hair_var = tk.StringVar(value="")
        self._fusion_hair_var.trace_add("write", lambda *_: self._update_fusion_button())
        self._fusion_hair_menu = tk.OptionMenu(self._fusion_hair_frame, self._fusion_hair_var, *HAIR_LENGTHS)
        self._fusion_hair_menu.configure(width=12, bg="#1E1E1E", fg=TEXT_COLOR)
        self._fusion_hair_menu.pack(side="left")

        # Images row
        images_frame = tk.Frame(parent, bg=BG_COLOR)
        images_frame.pack(fill="both", expand=True, padx=20)

        # Left image slot
        left_frame = tk.Frame(images_frame, bg=CARD_BG, padx=8, pady=8)
        left_frame.pack(side="left", padx=(0, 10))

        tk.Label(left_frame, text="Left Character", bg=CARD_BG, fg=TEXT_COLOR, font=SECTION_FONT).pack(pady=(0, 6))

        left_slot = tk.Frame(left_frame, bg="#1E1E1E", width=FUSION_SLOT_WIDTH, height=FUSION_SLOT_HEIGHT)
        left_slot.pack_propagate(False)
        left_slot.pack()

        self._fusion_left_label = tk.Label(
            left_slot, text="Click to\nbrowse...", bg="#1E1E1E", fg=TEXT_SECONDARY, font=BODY_FONT, cursor="hand2"
        )
        self._fusion_left_label.pack(expand=True)
        self._fusion_left_label.bind("<Button-1>", lambda e: self._browse_fusion_left())
        left_slot.bind("<Button-1>", lambda e: self._browse_fusion_left())

        # Result image slot (center)
        result_frame = tk.Frame(images_frame, bg=CARD_BG, padx=8, pady=8)
        result_frame.pack(side="left", expand=True)

        tk.Label(result_frame, text="Fused Result", bg=CARD_BG, fg=ACCENT_COLOR, font=SECTION_FONT).pack(pady=(0, 6))

        self._fusion_result_slot = tk.Frame(result_frame, bg="#1E1E1E", width=FUSION_SLOT_WIDTH, height=FUSION_SLOT_HEIGHT)
        self._fusion_result_slot.pack_propagate(False)
        self._fusion_result_slot.pack()

        self._fusion_result_label = tk.Label(
            self._fusion_result_slot, text="Result will\nappear here", bg="#1E1E1E", fg=TEXT_SECONDARY, font=BODY_FONT
        )
        self._fusion_result_label.pack(expand=True)

        # Right image slot
        right_frame = tk.Frame(images_frame, bg=CARD_BG, padx=8, pady=8)
        right_frame.pack(side="right", padx=(10, 0))

        tk.Label(right_frame, text="Right Character", bg=CARD_BG, fg=TEXT_COLOR, font=SECTION_FONT).pack(pady=(0, 6))

        right_slot = tk.Frame(right_frame, bg="#1E1E1E", width=FUSION_SLOT_WIDTH, height=FUSION_SLOT_HEIGHT)
        right_slot.pack_propagate(False)
        right_slot.pack()

        self._fusion_right_label = tk.Label(
            right_slot, text="Click to\nbrowse...", bg="#1E1E1E", fg=TEXT_SECONDARY, font=BODY_FONT, cursor="hand2"
        )
        self._fusion_right_label.pack(expand=True)
        self._fusion_right_label.bind("<Button-1>", lambda e: self._browse_fusion_right())
        right_slot.bind("<Button-1>", lambda e: self._browse_fusion_right())

        # Control row (fusion button + status)
        control_frame = tk.Frame(parent, bg=BG_COLOR)
        control_frame.pack(fill="x", padx=20, pady=(12, 0))

        self._fusion_btn = create_primary_button(control_frame, "FUSION!", self._run_fusion, width=16, large=True)
        self._fusion_btn.pack()
        self._fusion_btn.configure(state="disabled")

        self._fusion_status_label = tk.Label(
            control_frame, text="Select two images and fill in settings", bg=BG_COLOR, fg=TEXT_SECONDARY, font=SMALL_FONT
        )
        self._fusion_status_label.pack(pady=(8, 0))

        # NSFW content warning for fusion
        tk.Label(
            control_frame,
            text="Gemini cannot process nudity or minimal clothing. Use clothed character images.",
            bg=BG_COLOR,
            fg=WARNING_TEXT,
            font=SMALL_FONT,
        ).pack(pady=(4, 0))

    def _select_source_card(self, card: OptionCard, mode: str) -> None:
        """Handle source card selection."""
        self.state.source_mode = mode

        for c in self._source_cards:
            c.selected = (c == card)

        # Show/hide panels based on mode
        if mode == "image":
            self._image_preview_frame.pack(pady=(16, 0))
            self._fusion_frame.pack_forget()
        elif mode == "fusion":
            self._image_preview_frame.pack_forget()
            self._fusion_frame.pack(pady=(16, 0), fill="both", expand=True)
            self._update_fusion_button()
        else:
            self._image_preview_frame.pack_forget()
            self._fusion_frame.pack_forget()

    def _browse_image(self) -> None:
        """Open file dialog to select source image."""
        filename = filedialog.askopenfilename(
            title="Choose character source image",
            filetypes=[
                ("Images", "*.png *.jpg *.jpeg *.webp"),
                ("PNG", "*.png"),
                ("JPEG", "*.jpg *.jpeg"),
                ("WEBP", "*.webp"),
                ("All files", "*.*"),
            ],
        )
        if filename:
            self.state.image_path = Path(filename)
            self._image_preview_label.configure(text=f"Selected: {self.state.image_path.name}", fg=TEXT_COLOR)
            self._show_image_preview(Path(filename))

    def _show_image_preview(self, image_path: Path) -> None:
        """Display a thumbnail preview of the selected image."""
        try:
            img = Image.open(image_path).convert("RGBA")
            max_h = 250
            w, h = img.size
            if h > max_h:
                scale = max_h / h
                img = img.resize((int(w * scale), max_h), Image.LANCZOS)

            self._tk_preview_img = ImageTk.PhotoImage(img)
            self._preview_image_display.configure(image=self._tk_preview_img)
        except Exception as e:
            self._image_preview_label.configure(text=f"Error loading preview: {e}", fg=ERROR_TEXT)

    # -------------------------------------------------------------------------
    # Fusion methods
    # -------------------------------------------------------------------------

    def _set_fusion_voice(self, voice: str) -> None:
        """Handle fusion voice selection."""
        self._fusion_voice_var.set(voice)
        self.state.voice = voice
        self._fusion_voice_indicator.configure(text=f"({voice.capitalize()})")

        self._update_fusion_archetype_menu()
        self._update_fusion_hair_visibility()

        if not self._fusion_name_var.get().strip():
            name = pick_random_name(voice, self._girl_names, self._boy_names)
            self._fusion_name_var.set(name)

        self._fusion_name_entry.focus_set()
        self._update_fusion_button()

    def _update_fusion_hair_visibility(self) -> None:
        """Show hair length dropdown for girl voice, hide for boy."""
        voice = self._fusion_voice_var.get() if self._fusion_voice_var else ""
        if voice == "girl":
            self._fusion_hair_frame.pack(side="left", padx=(20, 0))
        else:
            self._fusion_hair_frame.pack_forget()
            self._fusion_hair_var.set("")

    def _update_fusion_archetype_menu(self) -> None:
        """Update fusion archetype menu based on voice."""
        menu = self._fusion_arch_menu["menu"]
        menu.delete(0, "end")

        voice = self._fusion_voice_var.get()
        if voice == "girl":
            labels = [label for (label, g) in GENDER_ARCHETYPES if g == "f"]
            self.state.gender_style = "f"
        elif voice == "boy":
            labels = [label for (label, g) in GENDER_ARCHETYPES if g == "m"]
            self.state.gender_style = "m"
        else:
            labels = []
            self.state.gender_style = ""

        self._fusion_arch_var.set(labels[0] if labels else "")
        for lbl in labels:
            menu.add_command(label=lbl, command=lambda v=lbl: self._on_fusion_arch_select(v))

    def _on_fusion_arch_select(self, value: str) -> None:
        """Handle archetype selection in fusion."""
        self._fusion_arch_var.set(value)
        self._update_fusion_button()

    def _browse_fusion_left(self) -> None:
        """Browse for left fusion character image."""
        path = filedialog.askopenfilename(
            title="Select Left Character Image",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp"), ("All files", "*.*")],
        )
        if path:
            self.state.fusion_left_path = Path(path)
            self._display_fusion_image(Path(path), "left")
            self._update_fusion_button()

    def _browse_fusion_right(self) -> None:
        """Browse for right fusion character image."""
        path = filedialog.askopenfilename(
            title="Select Right Character Image",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp"), ("All files", "*.*")],
        )
        if path:
            self.state.fusion_right_path = Path(path)
            self._display_fusion_image(Path(path), "right")
            self._update_fusion_button()

    def _display_fusion_image(self, path: Path, slot: str) -> None:
        """Display an image in a fusion slot."""
        try:
            img = Image.open(path).convert("RGBA")
            img.thumbnail((FUSION_SLOT_WIDTH, FUSION_SLOT_HEIGHT), Image.Resampling.LANCZOS)
            tk_img = ImageTk.PhotoImage(img)

            if slot == "left":
                self._fusion_left_tk_img = tk_img
                self._fusion_left_label.configure(image=tk_img, text="")
            elif slot == "right":
                self._fusion_right_tk_img = tk_img
                self._fusion_right_label.configure(image=tk_img, text="")
            elif slot == "result":
                self._fusion_result_tk_img = tk_img
                self._fusion_result_label.configure(image=tk_img, text="")
        except Exception as e:
            log_error("SourceStep", f"Failed to load fusion image: {e}")
            messagebox.showerror("Error", f"Failed to load image:\n{e}")

    def _update_fusion_button(self) -> None:
        """Update fusion button state based on inputs."""
        has_left = self.state.fusion_left_path is not None
        has_right = self.state.fusion_right_path is not None
        has_voice = bool(self._fusion_voice_var.get())
        has_name = bool(self._fusion_name_var.get().strip())
        has_arch = bool(self._fusion_arch_var.get())
        has_hair = self._fusion_voice_var.get() != "girl" or bool(self._fusion_hair_var.get())
        has_result = self.state.fusion_result_image is not None

        if has_left and has_right and has_voice and has_name and has_arch and has_hair:
            self._fusion_btn.configure(state="normal")
            if has_result:
                self._fusion_status_label.configure(
                    text="Fusion complete! Click Next to continue, or FUSION! to regenerate.", fg=ACCENT_COLOR
                )
            else:
                self._fusion_status_label.configure(text="Ready to fuse! Click FUSION! to generate.", fg=TEXT_SECONDARY)
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
            self._fusion_status_label.configure(text=f"Missing: {', '.join(missing)}", fg=TEXT_SECONDARY)

    def _run_fusion(self) -> None:
        """Start the fusion process."""
        if self._is_fusing:
            return

        # Save settings to state
        self.state.voice = self._fusion_voice_var.get()
        self.state.display_name = self._fusion_name_var.get().strip()
        self.state.archetype_label = self._fusion_arch_var.get()
        self.state.hair_length = self._fusion_hair_var.get() if self._fusion_voice_var.get() == "girl" else ""

        self._is_fusing = True
        self._fusion_btn.configure(state="disabled")
        self._fusion_status_label.configure(text="Generating fused character...", fg=ACCENT_COLOR)
        self._show_fusion_loading()

        thread = threading.Thread(target=self._generate_fusion, daemon=True)
        thread.start()

    def _show_fusion_loading(self) -> None:
        """Show loading overlay on the fusion result slot."""
        if self._fusion_result_slot is None:
            return

        # Remove any existing overlay
        self._hide_fusion_loading()

        # Create semi-transparent overlay
        self._fusion_loading_overlay = tk.Frame(self._fusion_result_slot, bg=OVERLAY_BG)
        self._fusion_loading_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)

        tk.Label(
            self._fusion_loading_overlay,
            text="Fusing\ncharacters...",
            bg=OVERLAY_BG,
            fg=TEXT_COLOR,
            font=BODY_FONT,
        ).place(relx=0.5, rely=0.5, anchor="center")

    def _hide_fusion_loading(self) -> None:
        """Hide the fusion result loading overlay."""
        if self._fusion_loading_overlay is not None:
            try:
                self._fusion_loading_overlay.destroy()
            except tk.TclError:
                pass
            self._fusion_loading_overlay = None

    def _generate_fusion(self) -> None:
        """Generate the fused character in background thread."""
        try:
            from ...api.gemini_client import call_gemini_fusion, load_image_as_base64
            from ...api.prompt_builders import build_fusion_prompt
            from ...config import load_background_color

            api_key = self.state.api_key
            if not api_key:
                from ...api.gemini_client import get_api_key
                api_key = get_api_key(use_gui=True)

            left_b64 = load_image_as_base64(self.state.fusion_left_path)
            right_b64 = load_image_as_base64(self.state.fusion_right_path)

            prompt = build_fusion_prompt(
                archetype_label=self.state.archetype_label,
                gender_style=self.state.gender_style,
                hair_length=self.state.hair_length,
                background_color=load_background_color(),
            )

            result_bytes = call_gemini_fusion(
                api_key=api_key,
                prompt=prompt,
                left_image_b64=left_b64,
                right_image_b64=right_b64,
                skip_background_removal=True,
            )

            if result_bytes:
                result_img = Image.open(BytesIO(result_bytes)).convert("RGBA")
                self.state.fusion_result_image = result_img
                self.schedule_callback(lambda: self._on_fusion_complete(result_img))
            else:
                self.schedule_callback(lambda: self._on_fusion_error("No image returned"))

        except GeminiSafetyError:
            safety_msg = (
                "Gemini blocked this content due to safety filters.\n\n"
                "This usually happens with revealing clothing, suggestive "
                "poses, or nudity. Try different input images."
            )
            log_error("Fusion blocked by safety filters")
            self.schedule_callback(lambda: self._on_fusion_error(safety_msg))
        except Exception as e:
            error_msg = str(e)
            log_error(f"Fusion failed: {error_msg}")
            self.schedule_callback(lambda: self._on_fusion_error(error_msg))

    def _on_fusion_complete(self, result_img: Image.Image) -> None:
        """Handle successful fusion."""
        self._is_fusing = False
        self._hide_fusion_loading()
        self._fusion_btn.configure(state="normal")
        self._fusion_status_label.configure(
            text="Fusion complete! Click Next to continue, or FUSION! to regenerate.", fg=ACCENT_COLOR
        )

        img_copy = result_img.copy()
        img_copy.thumbnail((FUSION_SLOT_WIDTH, FUSION_SLOT_HEIGHT), Image.Resampling.LANCZOS)
        self._fusion_result_tk_img = ImageTk.PhotoImage(img_copy)
        self._fusion_result_label.configure(image=self._fusion_result_tk_img, text="")

        log_info("Character fusion complete")

    def _on_fusion_error(self, error: str) -> None:
        """Handle fusion error."""
        self._is_fusing = False
        self._hide_fusion_loading()
        self._fusion_btn.configure(state="normal")
        self._fusion_status_label.configure(text=f"Fusion failed: {error[:50]}...", fg=ERROR_TEXT)
        log_error("Fusion", f"Failed: {error}")
        messagebox.showerror("Fusion Failed", f"Failed to generate fused character:\n{error}")

    # -------------------------------------------------------------------------
    # Step lifecycle
    # -------------------------------------------------------------------------

    def on_enter(self) -> None:
        """Restore state when entering this step."""
        # Restore image mode state
        if self.state.source_mode == "image" and self.state.image_path:
            self._image_preview_label.configure(text=f"Selected: {self.state.image_path.name}", fg=TEXT_COLOR)
            self._show_image_preview(self.state.image_path)

        # Restore fusion mode state
        if self.state.source_mode == "fusion":
            # Re-select the fusion card
            for card in self._source_cards:
                if "Fusion" in card._title:
                    card.selected = True
                else:
                    card.selected = False

            # Show fusion panel
            self._image_preview_frame.pack_forget()
            self._fusion_frame.pack(pady=(16, 0), fill="both", expand=True)

            # Restore settings
            if self.state.voice:
                self._fusion_voice_var.set(self.state.voice)
                self._fusion_voice_indicator.configure(text=f"({self.state.voice.capitalize()})")
                self._update_fusion_archetype_menu()

            if self.state.display_name:
                self._fusion_name_var.set(self.state.display_name)

            if self.state.archetype_label:
                self._fusion_arch_var.set(self.state.archetype_label)

            # Restore images
            if self.state.fusion_left_path:
                self._display_fusion_image(self.state.fusion_left_path, "left")

            if self.state.fusion_right_path:
                self._display_fusion_image(self.state.fusion_right_path, "right")

            if self.state.fusion_result_image:
                img_copy = self.state.fusion_result_image.copy()
                img_copy.thumbnail((FUSION_SLOT_WIDTH, FUSION_SLOT_HEIGHT), Image.Resampling.LANCZOS)
                self._fusion_result_tk_img = ImageTk.PhotoImage(img_copy)
                self._fusion_result_label.configure(image=self._fusion_result_tk_img, text="")

            self._update_fusion_button()

    def validate(self) -> bool:
        """Validate step before proceeding."""
        if self.state.source_mode == "image" and not self.state.image_path:
            messagebox.showerror("No Image Selected", "Please select a source image.")
            return False

        if self.state.source_mode == "fusion":
            # Check settings
            if not self._fusion_voice_var.get():
                messagebox.showerror("Missing Voice", "Please select a voice (Girl or Boy).")
                return False

            name_value = self._fusion_name_var.get().strip()
            if not name_value:
                messagebox.showerror("Missing Name", "Please enter a name for the character.")
                return False

            if not self._fusion_arch_var.get():
                messagebox.showerror("Missing Archetype", "Please select an archetype.")
                return False

            if self._fusion_voice_var.get() == "girl" and not self._fusion_hair_var.get():
                messagebox.showerror("Missing Hair Length", "Please select a hair length.")
                return False

            if self.state.fusion_result_image is None:
                messagebox.showerror(
                    "No Fusion Result",
                    "Please click FUSION! to generate the character before continuing."
                )
                return False

            # Save final settings
            self.state.voice = self._fusion_voice_var.get()
            self.state.display_name = name_value
            self.state.archetype_label = self._fusion_arch_var.get()
            self.state.hair_length = self._fusion_hair_var.get() if self._fusion_voice_var.get() == "girl" else ""

        return True


# =============================================================================
# Step 3: Setup (Crop and Modify)
# =============================================================================

class SetupStep(WizardStep):
    """Step 3: Handle image crop and optional modifications. Settings are read-only."""

    STEP_ID = "setup"
    STEP_TITLE = "Setup"
    STEP_NUMBER = 3
    STEP_TIP = (
        "Review your character image. Use Crop to reframe, or add a text "
        "description to guide how Gemini styles the character."
    )
    STEP_HELP = """Character Setup

This step prepares the base image for sprite generation.

YOUR SETTINGS
The character settings (Voice, Name, Archetype) were configured in the
previous step and are shown at the top for reference.

═══════════════════════════════════════════════════
CROP TOOL - CROP AT MID-THIGH!
═══════════════════════════════════════════════════

Click anywhere on the image to set a horizontal crop line (shown in red).

IMPORTANT: Crop at mid-thigh level! This ensures:
• Consistent framing across all outfits and expressions
• No feet visible (feet cause issues with background removal)
• Proper positioning for visual novel dialogue scenes

How to use:
1. Click on the image where you want to crop (mid-thigh recommended)
2. The red line shows where the image will be cut
3. Click "Accept Crop" to apply
4. Click "Restore Original" to undo and try again

The Next button is disabled until you accept the crop.

MODIFY CHARACTER (Optional)
For Image mode and Fusion mode, you can optionally modify the character
by typing instructions (e.g., "change hair to blue", "add glasses") and
clicking "Modify Character".

Use "Reset to Normalized" to undo modifications and start fresh.

For Text Prompt Mode:
Fill in the "Character Description" box with details about appearance,
then click "Generate Character". Once generated, use the crop tool
as described above.

MODE DIFFERENCES
- Image mode: Loads your normalized image for cropping/modification
- Fusion mode: Loads the fused result (no normalization needed)
- Prompt mode: Generate a character from text description first

ADD-TO-EXISTING MODE
When adding to an existing character:
- Full-size backup images appear first (highest quality, labeled "Full Size")
- Select a base sprite, then click "Normalize" to prepare it
- Normalization standardizes the image to match AI output resolution
- Review the normalized result, then click "Accept" to proceed
- You can click "Regenerate" to re-normalize if needed
- The Next button is disabled until you accept a normalized result

ST STYLE TOGGLE (Prompt Mode Only)
The "Use ST style references" checkbox controls the art style when generating from a text description:
- Checked (default): Uses Student Transfer reference art for consistent style
- Unchecked: No style references - describe any art style you want

GOING BACK
If you go back to a previous step and change settings (like outfit descriptions or the base image), the tool will automatically detect changes and regenerate affected content when you return.

Click Next when your character looks right."""

    def __init__(self, wizard, state: WizardState):
        super().__init__(wizard, state)
        # Concept text for prompt mode
        self._concept_text: Optional[tk.Text] = None
        self._concept_frame: Optional[tk.Frame] = None

        # Two-column layout frames
        self._left_col: Optional[tk.Frame] = None
        self._right_col: Optional[tk.Frame] = None

        # Settings display (read-only)
        self._settings_display_frame: Optional[tk.Frame] = None

        # Crop-related
        self._crop_frame: Optional[tk.Frame] = None
        self._crop_canvas: Optional[tk.Canvas] = None
        self._crop_image: Optional[ImageTk.PhotoImage] = None
        self._crop_original_img: Optional[Image.Image] = None
        self._crop_guide_line_id: Optional[int] = None
        self._crop_scale: float = 1.0
        self._crop_disp_w: int = 0
        self._crop_disp_h: int = 0
        self._crop_status_label: Optional[tk.Label] = None

        # Crop accept/restore
        self._crop_accepted: bool = False
        self._crop_buttons_frame: Optional[tk.Frame] = None
        self._accept_crop_btn: Optional[tk.Button] = None
        self._restore_btn: Optional[tk.Button] = None
        self._original_image_backup: Optional[Image.Image] = None

        # For prompt mode: generation
        self._generate_btn: Optional[tk.Button] = None
        self._generation_status: Optional[tk.Label] = None
        self._generated_image: Optional[Image.Image] = None
        self._use_st_style_var: Optional[tk.IntVar] = None  # ST style toggle

        # For image mode: modification (normalization moved to SettingsStep)
        self._image_modify_frame: Optional[tk.Frame] = None
        self._modify_text: Optional[tk.Text] = None
        self._modify_btn: Optional[tk.Button] = None
        self._reset_to_normalized_btn: Optional[tk.Button] = None
        self._image_status: Optional[tk.Label] = None
        self._normalized_image: Optional[Image.Image] = None
        self._content_visible: bool = False  # Track if step content is visible

        # For add-to-existing mode: sprite selector
        self._sprite_selector_frame: Optional[tk.Frame] = None
        self._sprite_cards_container: Optional[tk.Frame] = None
        self._sprite_tk_images: List[ImageTk.PhotoImage] = []
        self._sprite_preview_frame: Optional[tk.Frame] = None
        self._sprite_preview_canvas: Optional[tk.Canvas] = None
        self._sprite_preview_tk_img: Optional[ImageTk.PhotoImage] = None
        self._selected_sprite_image: Optional[Image.Image] = None
        self._sprite_accept_btn: Optional[tk.Button] = None
        self._sprite_accepted: bool = False

        # For add-to-existing mode: normalization comparison UI
        self._normalize_btn: Optional[tk.Button] = None
        self._normalized_preview_frame: Optional[tk.Frame] = None
        self._normalized_preview_canvas: Optional[tk.Canvas] = None
        self._normalized_preview_tk_img: Optional[ImageTk.PhotoImage] = None
        self._normalized_sprite_image: Optional[Image.Image] = None
        self._normalize_loading_overlay: Optional[tk.Frame] = None
        self._is_normalizing_add_existing: bool = False
        self._normalize_regen_btn: Optional[tk.Button] = None
        self._normalize_accept_btn: Optional[tk.Button] = None

    def build_ui(self, parent: tk.Frame) -> None:
        parent.configure(bg=BG_COLOR)

        # Title
        tk.Label(
            parent,
            text="Character Setup",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=PAGE_TITLE_FONT,
        ).pack(pady=(0, 8))

        self._build_tip_bar(parent)

        # Two-column container
        columns = tk.Frame(parent, bg=BG_COLOR)
        columns.pack(fill="both", expand=True, padx=20)

        # === LEFT COLUMN: Settings display + Modify/Concept ===
        self._left_col = tk.Frame(columns, bg=BG_COLOR)
        self._left_col.pack(side="left", fill="both", expand=True, padx=(0, 20))

        # Settings display (read-only) - populated in on_enter
        self._settings_display_frame = tk.Frame(self._left_col, bg=CARD_BG, padx=16, pady=12)
        self._settings_display_frame.pack(fill="x", pady=(0, 12))

        tk.Label(
            self._settings_display_frame,
            text="Character Settings",
            bg=CARD_BG,
            fg=ACCENT_COLOR,
            font=SECTION_FONT,
        ).pack(anchor="w", pady=(0, 8))

        # Settings labels will be created/updated in on_enter
        self._voice_label = tk.Label(
            self._settings_display_frame,
            text="Voice: --",
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=BODY_FONT,
        )
        self._voice_label.pack(anchor="w", pady=2)

        self._name_label = tk.Label(
            self._settings_display_frame,
            text="Name: --",
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=BODY_FONT,
        )
        self._name_label.pack(anchor="w", pady=2)

        self._archetype_label = tk.Label(
            self._settings_display_frame,
            text="Archetype: --",
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=BODY_FONT,
        )
        self._archetype_label.pack(anchor="w", pady=2)

        self._hair_length_label = tk.Label(
            self._settings_display_frame,
            text="Hair Length: --",
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=BODY_FONT,
        )
        self._hair_length_label.pack(anchor="w", pady=2)

        # Concept text (only shown for prompt mode)
        self._concept_frame = tk.Frame(self._left_col, bg=BG_COLOR)

        tk.Label(
            self._concept_frame,
            text="Character Description:",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=BODY_FONT,
        ).pack(anchor="w", pady=(12, 6))

        tk.Label(
            self._concept_frame,
            text="Describe appearance, style, personality traits, etc.",
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        ).pack(anchor="w", pady=(0, 6))

        # Gemini safety warning
        tk.Label(
            self._concept_frame,
            text="Note: Gemini may refuse to generate characters with certain descriptions. "
                 "If generation fails, try adjusting your description.",
            bg=BG_COLOR,
            fg=WARNING_TEXT,  # Warning orange
            font=SMALL_FONT,
            wraplength=350,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        self._concept_text = tk.Text(
            self._concept_frame,
            height=5,
            width=40,
            wrap="word",
            bg="#1E1E1E",
            fg=TEXT_COLOR,
            insertbackground=TEXT_COLOR,
            font=BODY_FONT,
        )
        self._concept_text.pack(fill="x")

        # ST style toggle (prompt mode only)
        self._use_st_style_var = tk.IntVar(value=1)  # Default ON
        st_style_chk = ttk.Checkbutton(
            self._concept_frame,
            text="Use ST style references",
            variable=self._use_st_style_var,
            style="Dark.TCheckbutton",
        )
        st_style_chk.pack(anchor="w", pady=(10, 0))

        tk.Label(
            self._concept_frame,
            text="When checked, uses Student Transfer reference art. Uncheck to use any style.",
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        ).pack(anchor="w", pady=(2, 0))

        # Generate button (prompt mode only)
        self._generate_btn = create_primary_button(
            self._concept_frame,
            "Generate Character",
            self._on_generate_click,
            width=18,
        )
        self._generate_btn.pack(pady=(10, 0))

        self._generation_status = tk.Label(
            self._concept_frame,
            text="",
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        )
        self._generation_status.pack(pady=(6, 0))

        # === RIGHT COLUMN: Image preview / Crop ===
        self._right_col = tk.Frame(columns, bg=BG_COLOR)
        self._right_col.pack(side="left", fill="both", expand=True)

        # Crop section
        self._crop_frame = tk.Frame(self._right_col, bg=BG_COLOR)

        tk.Label(
            self._crop_frame,
            text="Set Crop Line",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=SECTION_FONT,
        ).pack(pady=(0, 6))

        tk.Label(
            self._crop_frame,
            text="⚠️ IMPORTANT: Click to set crop at MID-THIGH level, then click Accept Crop.\n"
                 "Do NOT include feet - they cause issues with background removal!",
            bg=BG_COLOR,
            fg=WARNING_TEXT,  # Warning orange
            font=SMALL_FONT,
            justify="center",
        ).pack(pady=(0, 6))

        # Canvas container
        crop_canvas_container = tk.Frame(self._crop_frame, bg=CARD_BG, padx=2, pady=2)
        crop_canvas_container.pack()

        self._crop_canvas = tk.Canvas(
            crop_canvas_container,
            width=400,
            height=500,
            bg="black",
            highlightthickness=0,
        )
        self._crop_canvas.pack()
        self._crop_canvas.bind("<Motion>", self._on_crop_motion)
        self._crop_canvas.bind("<Button-1>", self._on_crop_click)

        self._crop_status_label = tk.Label(
            self._crop_frame,
            text="",
            bg=BG_COLOR,
            fg=ACCENT_COLOR,
            font=SMALL_FONT,
        )
        self._crop_status_label.pack(pady=(6, 0))

        # Crop buttons (Accept / Restore)
        self._crop_buttons_frame = tk.Frame(self._crop_frame, bg=BG_COLOR)
        self._crop_buttons_frame.pack(pady=(6, 0))

        self._accept_crop_btn = create_primary_button(
            self._crop_buttons_frame,
            "Accept Crop",
            self._on_accept_crop,
            width=12,
        )
        self._accept_crop_btn.pack(side="left", padx=(0, 8))

        self._restore_btn = create_secondary_button(
            self._crop_buttons_frame,
            "Restore Original",
            self._on_restore_original,
            width=14,
        )
        # Restore button starts hidden
        self._restore_btn.pack_forget()

        # === Image Mode: Modify Character Section (shown in image mode only) ===
        self._image_modify_frame = tk.Frame(self._left_col, bg=BG_COLOR)
        # Will be packed in on_enter for image mode

        tk.Label(
            self._image_modify_frame,
            text="Modify Character (Optional)",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=SECTION_FONT,
        ).pack(anchor="w", pady=(12, 6))

        tk.Label(
            self._image_modify_frame,
            text="Describe changes to make (hair, clothes, features, etc.)",
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        ).pack(anchor="w", pady=(0, 6))

        self._modify_text = tk.Text(
            self._image_modify_frame,
            height=3,
            width=40,
            wrap="word",
            bg="#1E1E1E",
            fg=TEXT_COLOR,
            insertbackground=TEXT_COLOR,
            font=BODY_FONT,
        )
        self._modify_text.pack(fill="x")

        # Buttons row for modify and reset
        modify_btns_frame = tk.Frame(self._image_modify_frame, bg=BG_COLOR)
        modify_btns_frame.pack(pady=(8, 0))

        self._modify_btn = create_secondary_button(
            modify_btns_frame,
            "Modify Character",
            self._on_modify_click,
            width=16,
        )
        self._modify_btn.pack(side="left", padx=(0, 8))

        self._reset_to_normalized_btn = create_secondary_button(
            modify_btns_frame,
            "Reset to Normalized",
            self._on_reset_to_normalized,
            width=16,
        )
        self._reset_to_normalized_btn.pack(side="left")
        # Hidden initially until a modification is made
        self._reset_to_normalized_btn.pack_forget()

        self._image_status = tk.Label(
            self._image_modify_frame,
            text="",
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        )
        self._image_status.pack(pady=(6, 0))

        # === Add-to-Existing Mode: Sprite Selector ===
        self._sprite_selector_frame = tk.Frame(self._left_col, bg=BG_COLOR)
        # Will be packed in on_enter for add-to-existing mode

        tk.Label(
            self._sprite_selector_frame,
            text="Select Base Sprite",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=SECTION_FONT,
        ).pack(anchor="w", pady=(0, 6))

        tk.Label(
            self._sprite_selector_frame,
            text="Click on a sprite to use as the base for new outfits",
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        ).pack(anchor="w", pady=(0, 8))

        # Scrollable container for sprite cards
        sprite_scroll_outer = tk.Frame(self._sprite_selector_frame, bg=BG_COLOR)
        sprite_scroll_outer.pack(fill="both", expand=True)

        self._sprite_cards_canvas = tk.Canvas(
            sprite_scroll_outer, bg=BG_COLOR, highlightthickness=0, height=500,
        )
        sprite_scrollbar = ttk.Scrollbar(
            sprite_scroll_outer, orient="vertical", command=self._sprite_cards_canvas.yview,
        )
        self._sprite_cards_container = tk.Frame(self._sprite_cards_canvas, bg=BG_COLOR)
        self._sprite_cards_container.bind(
            "<Configure>",
            lambda e: self._sprite_cards_canvas.configure(
                scrollregion=self._sprite_cards_canvas.bbox("all")
            ),
        )
        self._sprite_cards_canvas.create_window(
            (0, 0), window=self._sprite_cards_container, anchor="nw",
        )
        self._sprite_cards_canvas.configure(yscrollcommand=sprite_scrollbar.set)

        self._sprite_cards_canvas.pack(side="left", fill="both", expand=True)
        sprite_scrollbar.pack(side="right", fill="y")

        # Mouse wheel scrolling for sprite cards
        def _on_sprite_mousewheel(event):
            self._sprite_cards_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        self._sprite_cards_canvas.bind("<MouseWheel>", _on_sprite_mousewheel)
        self._sprite_cards_container.bind("<MouseWheel>", _on_sprite_mousewheel)
        self._sprite_mw_handler = _on_sprite_mousewheel

        # === Add-to-Existing Mode: Sprite Preview (Two-Panel Normalization) ===
        self._sprite_preview_frame = tk.Frame(self._right_col, bg=BG_COLOR)
        # Will be packed in on_enter for add-to-existing mode

        # Two side-by-side panels
        panels_row = tk.Frame(self._sprite_preview_frame, bg=BG_COLOR)
        panels_row.pack(fill="both", expand=True)

        # --- Left panel: Selected Base ---
        left_panel = tk.Frame(panels_row, bg=BG_COLOR)
        left_panel.pack(side="left", fill="both", expand=True, padx=(0, 6))

        tk.Label(
            left_panel,
            text="Selected Base",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=SECTION_FONT,
        ).pack(pady=(0, 4))

        left_canvas_container = tk.Frame(left_panel, bg=CARD_BG, padx=2, pady=2)
        left_canvas_container.pack()

        self._sprite_preview_canvas = tk.Canvas(
            left_canvas_container,
            width=340,
            height=500,
            bg="black",
            highlightthickness=0,
        )
        self._sprite_preview_canvas.pack()

        # "Normalize" button under left canvas
        self._normalize_btn = create_primary_button(
            left_panel,
            "Normalize",
            self._on_normalize_click,
            width=14,
        )
        self._normalize_btn.pack(pady=(8, 0))
        self._normalize_btn.configure(state="disabled")

        # --- Right panel: Normalized Base ---
        right_panel = tk.Frame(panels_row, bg=BG_COLOR)
        right_panel.pack(side="left", fill="both", expand=True, padx=(6, 0))

        tk.Label(
            right_panel,
            text="Normalized Base",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=SECTION_FONT,
        ).pack(pady=(0, 4))

        self._normalized_preview_frame = tk.Frame(right_panel, bg=CARD_BG, padx=2, pady=2)
        self._normalized_preview_frame.pack()

        self._normalized_preview_canvas = tk.Canvas(
            self._normalized_preview_frame,
            width=340,
            height=500,
            bg="black",
            highlightthickness=0,
        )
        self._normalized_preview_canvas.pack()

        # Buttons row under right canvas: Regenerate + Accept
        right_btn_row = tk.Frame(right_panel, bg=BG_COLOR)
        right_btn_row.pack(pady=(8, 0))

        self._normalize_regen_btn = create_secondary_button(
            right_btn_row,
            "Regenerate",
            self._on_regenerate_click,
            width=11,
        )
        self._normalize_regen_btn.pack(side="left", padx=(0, 6))
        self._normalize_regen_btn.configure(state="disabled")

        self._normalize_accept_btn = create_primary_button(
            right_btn_row,
            "Accept",
            self._on_accept_sprite_selection,
            width=11,
        )
        self._normalize_accept_btn.pack(side="left")
        self._normalize_accept_btn.configure(state="disabled")

    def _update_next_button_state(self) -> None:
        """Update the Next button state based on mode requirements."""
        # Add-to-existing mode: sprite selection must be accepted
        if self.state.is_adding_to_existing:
            if self._sprite_accepted:
                self.wizard._next_btn.configure(state="normal")
            else:
                self.wizard._next_btn.configure(state="disabled")
            return

        # Normal modes: crop must be accepted
        crop_ok = self._crop_accepted

        # Special case: if no image loaded yet (prompt mode before generation),
        # crop isn't required yet
        if self._crop_original_img is None:
            # For prompt mode, don't enable until image is generated and crop accepted
            if self.state.source_mode == "prompt":
                crop_ok = False  # Will be checked after generation

        if crop_ok:
            self.wizard._next_btn.configure(state="normal")
        else:
            self.wizard._next_btn.configure(state="disabled")

    def _on_generate_click(self) -> None:
        """Handle Generate button click for prompt mode."""
        # Get concept text
        concept = self._concept_text.get("1.0", "end").strip()
        if not concept:
            messagebox.showerror("Missing Description", "Please describe the character before generating.")
            return

        # Save concept to state (voice/name/archetype already set from SettingsStep)
        self.state.concept_text = concept

        # Disable button and show status
        self._generate_btn.configure(state="disabled")
        self._generation_status.configure(text="Generating character...", fg=TEXT_SECONDARY)
        self._crop_frame.winfo_toplevel().update()

        # Run generation in background thread
        import threading
        thread = threading.Thread(target=self._run_generation, daemon=True)
        thread.start()

    def _run_generation(self) -> None:
        """Run character generation in background thread."""
        try:
            from io import BytesIO
            from ...api.gemini_client import get_api_key, call_gemini_text_or_refs
            from ...api.prompt_builders import build_prompt_for_idea
            from ...processing.image_utils import get_reference_images_for_archetype

            log_generation_start("character_from_text")

            # Get API key (should already be set from earlier steps)
            api_key = self.state.api_key or get_api_key(use_gui=True)

            # Build prompt
            prompt = build_prompt_for_idea(
                concept=self.state.concept_text,
                archetype_label=self.state.archetype_label,
                gender_style=self.state.gender_style,
                hair_length=self.state.hair_length,
            )

            # Get reference images for this archetype (only if ST style toggle is ON)
            ref_images = []
            use_st_style = self._use_st_style_var and self._use_st_style_var.get() == 1
            if use_st_style:
                # Use the proper function to get archetype-specific reference images
                ref_images = get_reference_images_for_archetype(self.state.archetype_label)
                log_info(f"Loading style refs for archetype '{self.state.archetype_label}': found {len(ref_images)} images")
                if ref_images:
                    log_info(f"Reference images: {[p.name for p in ref_images]}")

            log_info(f"Generating character with ST style: {use_st_style}, refs: {len(ref_images)}")

            # Generate image (skip background removal - we'll do it later)
            result_bytes = call_gemini_text_or_refs(
                api_key=api_key,
                prompt=prompt,
                ref_images=ref_images if ref_images else None,
                skip_background_removal=True,  # Don't remove BG at this step
            )

            if result_bytes:
                # Convert bytes to PIL Image
                self._generated_image = Image.open(BytesIO(result_bytes)).convert("RGBA")
                log_generation_complete("character_from_text", True)
                # Schedule UI update on main thread
                self.schedule_callback(self._on_generation_complete)
            else:
                log_generation_complete("character_from_text", False, "No image returned")
                self.schedule_callback(lambda: self._on_generation_error("No image returned"))

        except GeminiSafetyError:
            safety_msg = (
                "Gemini blocked this content due to safety filters.\n\n"
                "This usually happens with revealing or suggestive descriptions. "
                "Try a more conservatively described character."
            )
            log_generation_complete("character_from_text", False, "Safety filter blocked")
            self.schedule_callback(lambda: self._on_generation_error(safety_msg))
        except Exception as e:
            error_msg = str(e)
            log_generation_complete("character_from_text", False, error_msg)
            self.schedule_callback(lambda: self._on_generation_error(error_msg))

    def _on_generation_complete(self) -> None:
        """Handle successful generation."""
        self._generation_status.configure(text="Character generated!", fg=ACCENT_COLOR)
        self._generate_btn.configure(state="normal")

        # Store as original for crop
        self._crop_original_img = self._generated_image.copy()
        self._original_image_backup = self._generated_image.copy()

        # Show crop section
        self._crop_frame.pack(fill="both", expand=True)
        self._display_crop_image()

        # Update Next button (will be disabled since crop not accepted yet)
        self._update_next_button_state()

    def _on_generation_error(self, error: str) -> None:
        """Handle generation error."""
        self._generation_status.configure(text=f"Error: {error}", fg=ERROR_TEXT)
        self._generate_btn.configure(state="normal")

    def _load_crop_image(self) -> None:
        """Load image from file for crop canvas (image mode)."""
        if not self.state.image_path or not self.state.image_path.exists():
            return

        try:
            self._crop_original_img = Image.open(self.state.image_path).convert("RGBA")
            self._original_image_backup = self._crop_original_img.copy()
        except Exception as e:
            self._crop_status_label.configure(text=f"Error loading: {e}", fg=ERROR_TEXT)
            return

        self._display_crop_image()

    def _display_crop_image(self) -> None:
        """Display the current image in the crop canvas."""
        if self._crop_original_img is None:
            return

        original_w, original_h = self._crop_original_img.size

        # Get screen size
        self._crop_canvas.update_idletasks()
        parent = self._crop_canvas.winfo_toplevel()
        sw, sh, *_ = get_primary_screen(parent)

        # Compute display size (fit in right column)
        max_w = int(sw * 0.35)
        max_h = int(sh * 0.55)
        scale = min(max_w / original_w, max_h / original_h, 1.0)
        self._crop_disp_w = max(1, int(original_w * scale))
        self._crop_disp_h = max(1, int(original_h * scale))
        self._crop_scale = original_h / max(1, self._crop_disp_h)

        # Resize canvas
        self._crop_canvas.configure(width=self._crop_disp_w, height=self._crop_disp_h)

        # Create display image
        disp_img = self._crop_original_img.resize(
            (self._crop_disp_w, self._crop_disp_h), Image.LANCZOS
        )
        self._crop_image = ImageTk.PhotoImage(disp_img)

        # Draw image
        self._crop_canvas.delete("all")
        self._crop_canvas.create_image(0, 0, anchor="nw", image=self._crop_image)
        self._crop_guide_line_id = None

        # Reset crop state
        self._crop_accepted = False
        self._restore_btn.pack_forget()
        self._accept_crop_btn.pack(side="left", padx=(0, 8))

        # Restore previous crop if exists
        if self.state.crop_y is not None:
            disp_y = int(self.state.crop_y / self._crop_scale)
            self._draw_crop_line(disp_y)
            self._crop_status_label.configure(text=f"Crop at y={self.state.crop_y}. Click to adjust.")
        else:
            self._crop_status_label.configure(text="Click to set crop line, then Accept Crop")

    def _draw_crop_line(self, y: int) -> None:
        """Draw the crop guide line at the given y position."""
        if self._crop_accepted:
            return  # Don't draw line if crop already accepted
        y = max(0, min(int(y), self._crop_disp_h))
        if self._crop_guide_line_id is None:
            self._crop_guide_line_id = self._crop_canvas.create_line(
                0, y, self._crop_disp_w, y,
                fill="#ff5555", width=3
            )
        else:
            self._crop_canvas.coords(self._crop_guide_line_id, 0, y, self._crop_disp_w, y)

    def _on_crop_motion(self, event) -> None:
        """Handle mouse motion over crop canvas."""
        if self._crop_original_img is None or self._crop_accepted:
            return
        self._draw_crop_line(event.y)

    def _on_crop_click(self, event) -> None:
        """Handle click on crop canvas to set crop position."""
        if self._crop_original_img is None or self._crop_accepted:
            return

        disp_y = max(0, min(event.y, self._crop_disp_h))
        self._draw_crop_line(disp_y)

        # Convert to original image coordinates
        real_y = int(disp_y * self._crop_scale)
        original_h = self._crop_original_img.size[1]

        # Store in state
        if real_y >= original_h - 5:
            # Clicked at/below bottom - no crop
            self.state.crop_y = None
            self._crop_status_label.configure(text="No crop (clicked at bottom)")
        else:
            self.state.crop_y = real_y
            self._crop_status_label.configure(text=f"Crop at y={real_y}. Click Accept to apply.")

    def _on_accept_crop(self) -> None:
        """Apply the current crop (or accept as-is if no crop set) and update the image."""
        if self._crop_original_img is None:
            return

        if self.state.crop_y is not None:
            # Apply the crop
            w, h = self._crop_original_img.size
            cropped = self._crop_original_img.crop((0, 0, w, self.state.crop_y))
            self._crop_original_img = cropped
            self._crop_status_label.configure(text="Crop applied. Click Restore to undo.")
        else:
            # Accept as-is without cropping
            self._crop_status_label.configure(text="Image accepted as-is. Click Restore to undo.")

        # Update display
        self._display_crop_image()
        self._crop_accepted = True
        self.state.crop_y = None  # Clear after applying

        # Update buttons
        self._accept_crop_btn.pack_forget()
        self._restore_btn.pack(side="left")

        # Enable Next button now that crop is accepted
        self._update_next_button_state()

    def _on_restore_original(self) -> None:
        """Restore the original uncropped image."""
        if self._original_image_backup is None:
            return

        self._crop_original_img = self._original_image_backup.copy()
        self._crop_accepted = False

        # Update display
        self._display_crop_image()

        # Update buttons
        self._restore_btn.pack_forget()
        self._accept_crop_btn.pack(side="left", padx=(0, 8))

        self._crop_status_label.configure(text="Original restored. Click to set new crop.")

        # Re-disable Next button since crop needs to be re-accepted
        self.wizard._next_btn.configure(state="disabled")

    def on_enter(self) -> None:
        """Prepare step based on source mode."""
        # Update settings display labels (read-only)
        self._voice_label.configure(text=f"Voice: {self.state.voice.capitalize() if self.state.voice else '--'}")
        self._name_label.configure(text=f"Name: {self.state.display_name or '--'}")
        self._archetype_label.configure(text=f"Archetype: {self.state.archetype_label or '--'}")
        hair = self.state.hair_length
        self._hair_length_label.configure(text=f"Hair Length: {hair.capitalize() if hair else '--'}")

        # Handle add-to-existing mode separately
        if self.state.is_adding_to_existing:
            self._update_tip(
                "Select a sprite from the existing character to use as the base for new outfits."
            )
            self._setup_add_to_existing_mode()
            return

        self._update_tip(self.STEP_TIP)
        if self.state.source_mode == "prompt":
            # Hide image modify frame (prompt mode uses concept frame)
            self._image_modify_frame.pack_forget()
            # Show concept frame with generate button
            self._concept_frame.pack(fill="x", pady=(12, 0))
            # Show crop frame (will be empty until generation)
            self._crop_frame.pack(fill="both", expand=True)
            self._content_visible = True
            # Clear canvas if no generated image yet
            if self._generated_image is None:
                self._crop_canvas.delete("all")
                self._crop_canvas.create_text(
                    140, 175,
                    text="Generate a character\nto see preview",
                    fill=TEXT_SECONDARY,
                    font=BODY_FONT,
                    justify="center",
                )
            else:
                # Generated image exists - check crop requirement
                self._update_next_button_state()
        elif self.state.source_mode == "fusion":
            # Fusion mode - use fusion result image (no normalization needed)
            self._concept_frame.pack_forget()

            if self.state.fusion_result_image is not None:
                # Use fusion result image directly (already has black background)
                self._normalized_image = self.state.fusion_result_image
                self._crop_original_img = self._normalized_image.copy()
                self._original_image_backup = self._normalized_image.copy()
                self._show_image_mode_content()
                self._display_crop_image()
                self._update_next_button_state()
            else:
                self._crop_frame.pack_forget()
                self._image_modify_frame.pack_forget()
        else:
            # Image mode
            self._concept_frame.pack_forget()

            if self.state.image_path:
                # Use normalized image from SettingsStep if available
                if self.state.normalized_image is not None:
                    self._normalized_image = self.state.normalized_image
                    self._crop_original_img = self._normalized_image.copy()
                    self._original_image_backup = self._normalized_image.copy()
                    self._show_image_mode_content()
                    self._display_crop_image()
                    self._update_next_button_state()
                else:
                    # No normalized image - use original (fallback)
                    self._show_image_mode_content()
                    self._load_crop_image()
                    self._update_next_button_state()
            else:
                self._crop_frame.pack_forget()
                self._image_modify_frame.pack_forget()

    def _show_image_mode_content(self) -> None:
        """Show the image mode content (modify frame and crop frame)."""
        if self._content_visible:
            return
        self._content_visible = True
        self._image_modify_frame.pack(fill="x", pady=(12, 0))
        self._crop_frame.pack(fill="both", expand=True)

    def _on_modify_click(self) -> None:
        """Handle Modify Character button click."""
        instructions = self._modify_text.get("1.0", "end").strip()
        if not instructions:
            messagebox.showerror("Missing Instructions", "Please describe the changes you want to make.")
            return

        # Disable button and show status
        self._modify_btn.configure(state="disabled")
        self._image_status.configure(text="Modifying character...", fg=TEXT_SECONDARY)
        self.wizard._next_btn.configure(state="disabled")

        # Run modification in background thread
        import threading
        thread = threading.Thread(target=lambda: self._run_modification(instructions), daemon=True)
        thread.start()

    def _run_modification(self, instructions: str) -> None:
        """Run character modification in background thread."""
        try:
            from io import BytesIO
            from ...api.gemini_client import get_api_key, call_gemini_image_edit, load_image_as_base64
            from ...api.prompt_builders import build_character_modification_prompt
            from ...config import load_background_color

            # Get API key
            api_key = self.state.api_key or get_api_key(use_gui=True)

            # Use current image (normalized or original)
            if self._crop_original_img is not None:
                # Save current image to temp buffer for base64 encoding
                buffer = BytesIO()
                self._crop_original_img.save(buffer, format="PNG")
                buffer.seek(0)
                import base64
                image_b64 = base64.b64encode(buffer.read()).decode("utf-8")
            else:
                # Fall back to source file
                image_b64 = load_image_as_base64(self.state.image_path)

            # Build modification prompt
            prompt = build_character_modification_prompt(instructions, background_color=load_background_color())

            # Call Gemini to modify
            result_bytes = call_gemini_image_edit(
                api_key=api_key,
                prompt=prompt,
                image_b64=image_b64,
                skip_background_removal=True,
            )

            if result_bytes:
                # Convert bytes to PIL Image
                modified_image = Image.open(BytesIO(result_bytes)).convert("RGBA")
                # Schedule UI update on main thread
                self.schedule_callback(lambda img=modified_image: self._on_modification_complete(img))
            else:
                self.schedule_callback(lambda: self._on_modification_error("No image returned"))

        except Exception as e:
            error_msg = str(e)
            self.schedule_callback(lambda: self._on_modification_error(error_msg))

    def _on_modification_complete(self, modified_image: Image.Image) -> None:
        """Handle successful modification."""
        self._image_status.configure(text="Character modified!", fg=ACCENT_COLOR)
        self._modify_btn.configure(state="normal")

        # Update current image (but keep _normalized_image as reset point)
        self._crop_original_img = modified_image.copy()
        # Also update backup so Restore Original gets the modified image
        self._original_image_backup = modified_image.copy()
        # Keep _normalized_image unchanged - it's the reset point for "Reset to Normalized"

        # Show reset button so user can go back to normalized version
        self._reset_to_normalized_btn.pack(side="left")

        # Show modified image and reset crop state
        self._crop_accepted = False
        self._display_crop_image()

        # Force UI refresh to ensure the new image displays
        self._crop_canvas.update_idletasks()

        # Update Next button (crop needs to be re-accepted)
        self._update_next_button_state()

    def _on_modification_error(self, error: str) -> None:
        """Handle modification error."""
        self._image_status.configure(text=f"Error: {error[:50]}...", fg=ERROR_TEXT)
        self._modify_btn.configure(state="normal")

    def _on_reset_to_normalized(self) -> None:
        """Reset to the normalized image (undo modifications)."""
        if self._normalized_image is None:
            return

        # Reset to normalized image
        self._crop_original_img = self._normalized_image.copy()
        self._crop_accepted = False

        # Update display
        self._display_crop_image()

        # Hide reset button
        self._reset_to_normalized_btn.pack_forget()

        self._image_status.configure(text="Reset to normalized image.", fg=ACCENT_COLOR)
        # Update Next button (crop needs to be re-accepted)
        self._update_next_button_state()

    def validate(self) -> bool:
        # Add-to-existing mode: just needs sprite selection accepted
        if self.state.is_adding_to_existing:
            if not self._sprite_accepted:
                messagebox.showerror("Selection Required", "Please accept your sprite selection before continuing.")
                return False
            # Sprite already saved to state in _on_accept_sprite_selection
            return True

        # Normal modes: Check crop is accepted
        if not self._crop_accepted:
            messagebox.showerror("Crop Required", "Please accept the crop before continuing.")
            return False

        if self.state.source_mode == "prompt":
            concept = self._concept_text.get("1.0", "end").strip()
            if not concept:
                messagebox.showerror(
                    "Missing Description",
                    "Please describe the character you want to create."
                )
                return False
            self.state.concept_text = concept

            # For prompt mode, require generated image
            if self._generated_image is None:
                messagebox.showerror(
                    "No Character Generated",
                    "Please click 'Generate Character' before continuing."
                )
                return False

            # Store the (possibly cropped) image for next steps
            self.state.generated_character_image = self._crop_original_img

            # Save to temp file for generation steps
            self._save_cropped_image_for_generation()

        # For image mode, store the (possibly cropped) image
        if self.state.source_mode == "image" and self._crop_original_img is not None:
            self.state.source_image = self._crop_original_img
            # Save to temp file for generation steps
            self._save_cropped_image_for_generation()

        # For fusion mode, store the (possibly cropped) fusion result
        if self.state.source_mode == "fusion" and self._crop_original_img is not None:
            self.state.fusion_result_image = self._crop_original_img
            # Save to temp file for generation steps
            self._save_cropped_image_for_generation()

        return True

    def _save_cropped_image_for_generation(self) -> None:
        """Save the cropped image to a temp path for generation steps."""
        if self._crop_original_img is None:
            return

        import tempfile
        import os

        # Create temp directory if needed
        temp_dir = Path(tempfile.gettempdir()) / "sprite_creator"
        temp_dir.mkdir(exist_ok=True)

        # Save cropped image
        temp_path = temp_dir / f"cropped_{id(self)}.png"
        self._crop_original_img.save(temp_path, format="PNG")
        self.state.cropped_image_path = temp_path
        # Reset base_pose_path so the review step picks up the new crop
        self.state.base_pose_path = None
        # Invalidate post-crop normalization so it re-runs on next outfit generation
        self.state.base_pose_normalized_post_crop = False

    # =========================================================================
    # Add-to-Existing Mode Methods
    # =========================================================================

    def _setup_add_to_existing_mode(self) -> None:
        """Set up the sprite selector UI for add-to-existing mode."""
        # Hide normal mode frames
        self._concept_frame.pack_forget()
        self._image_modify_frame.pack_forget()
        self._crop_frame.pack_forget()

        # Show sprite selector and preview frames
        self._sprite_selector_frame.pack(fill="both", expand=True, pady=(12, 0))
        self._sprite_preview_frame.pack(fill="both", expand=True)

        # Build sprite cards from existing poses
        self._build_sprite_cards()

        # Try to auto-load original.png (or legacy base.png) if it exists
        base_path = self.state.existing_character_folder / "original.png"
        if not base_path.exists():
            base_path = self.state.existing_character_folder / "base.png"  # Legacy fallback
        if base_path.exists():
            try:
                self._selected_sprite_image = Image.open(base_path).convert("RGBA")
                self._display_sprite_preview()
            except Exception:
                pass

        # If no base.png or failed to load, try first pose's expression 0
        if self._selected_sprite_image is None:
            self._load_first_available_sprite()

        # Update button states
        self._update_next_button_state()

    def _build_sprite_cards(self) -> None:
        """Build clickable sprite cards from existing poses.

        Priority order:
        1. Full-size backup images (highest quality, pre-scaling)
        2. Composites from character folder (outfit + face)
        3. base.png from character root
        """
        # Clear existing cards
        for widget in self._sprite_cards_container.winfo_children():
            widget.destroy()
        self._sprite_tk_images.clear()

        if not self.state.existing_character_folder:
            return

        char_folder = self.state.existing_character_folder

        cards_grid = tk.Frame(self._sprite_cards_container, bg=BG_COLOR)
        cards_grid.pack(fill="both", expand=True)

        row = 0
        col = 0
        max_cols = 3

        # 1. Full-size backup images (best quality - saved before scaling)
        backup_id = self.state.backup_id
        if backup_id:
            backup_dir = get_backup_dir(backup_id)
            if backup_dir.is_dir():
                poses = sorted(self.state.existing_poses if isinstance(self.state.existing_poses, list) else self.state.existing_poses.keys())
                for pose_letter in poses:
                    backup_face = backup_dir / pose_letter / "faces" / "face" / "0.png"
                    if backup_face.exists():
                        label = f"Pose {pose_letter.upper()} (Full Size)"
                        self._create_sprite_card(cards_grid, backup_face, label, row, col)
                        col += 1
                        if col >= max_cols:
                            col = 0
                            row += 1

        # 2. Composites from character folder (outfit + face for each pose)
        for pose_letter in sorted(self.state.existing_poses if isinstance(self.state.existing_poses, list) else self.state.existing_poses.keys()):
            pose_dir = char_folder / pose_letter

            if self._is_original_st_pose(pose_dir):
                contenders = self._generate_composite_contenders(pose_dir, pose_letter)
                for label, temp_path in contenders:
                    self._create_sprite_card(cards_grid, temp_path, label, row, col)
                    col += 1
                    if col >= max_cols:
                        col = 0
                        row += 1
            else:
                sprite_path = self._get_sprite_path_for_pose(pose_dir)
                if sprite_path:
                    label = f"Pose {pose_letter.upper()}"
                    self._create_sprite_card(cards_grid, sprite_path, label, row, col)
                    col += 1
                    if col >= max_cols:
                        col = 0
                        row += 1

        # 3. original.png (or legacy base.png) from character root (lowest priority)
        base_path = char_folder / "original.png"
        if not base_path.exists():
            base_path = char_folder / "base.png"  # Legacy fallback
        if base_path.exists():
            self._create_sprite_card(cards_grid, base_path, "Original", row, col)
            col += 1
            if col >= max_cols:
                col = 0
                row += 1

        # Bind mousewheel to all card widgets for scrolling
        self._bind_sprite_mousewheel(cards_grid)

    def _bind_sprite_mousewheel(self, widget: tk.Widget) -> None:
        """Recursively bind mousewheel scrolling to widget and all children."""
        if hasattr(self, '_sprite_mw_handler'):
            widget.bind("<MouseWheel>", self._sprite_mw_handler)
            for child in widget.winfo_children():
                self._bind_sprite_mousewheel(child)

    def _create_sprite_card(self, parent: tk.Frame, image_path: Path, label: str, row: int, col: int) -> None:
        """Create a clickable sprite card."""
        card = tk.Frame(parent, bg=CARD_BG, padx=4, pady=4)
        card.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")

        # Load and resize image for thumbnail
        try:
            img = Image.open(image_path).convert("RGBA")
            # Calculate thumbnail size (max 120x150)
            thumb_w, thumb_h = 120, 150
            img.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
            tk_img = ImageTk.PhotoImage(img)
            self._sprite_tk_images.append(tk_img)

            img_label = tk.Label(card, image=tk_img, bg=CARD_BG)
            img_label.pack()

            text_label = tk.Label(card, text=label, bg=CARD_BG, fg=TEXT_COLOR, font=SMALL_FONT)
            text_label.pack()

            # Bind click to select this sprite
            def on_click(event, path=image_path):
                self._on_sprite_card_click(path)

            card.bind("<Button-1>", on_click)
            img_label.bind("<Button-1>", on_click)
            text_label.bind("<Button-1>", on_click)

            # Hover effects
            def on_enter(event, c=card):
                c.configure(bg=ACCENT_COLOR)
                for child in c.winfo_children():
                    child.configure(bg=ACCENT_COLOR)

            def on_leave(event, c=card):
                c.configure(bg=CARD_BG)
                for child in c.winfo_children():
                    child.configure(bg=CARD_BG)

            card.bind("<Enter>", on_enter)
            card.bind("<Leave>", on_leave)
            card.configure(cursor="hand2")

        except Exception as e:
            # Show error placeholder
            tk.Label(card, text=f"Error\n{label}", bg=CARD_BG, fg=ERROR_TEXT, font=SMALL_FONT).pack()

    def _get_sprite_path_for_pose(self, pose_dir: Path) -> Optional[Path]:
        """Get a representative sprite path for a pose directory."""
        # Try expression 0 first, then 1
        face_dir = pose_dir / "faces" / "face"
        for expr_num in ["0", "1"]:
            for ext in [".png", ".webp"]:
                path = face_dir / f"{expr_num}{ext}"
                if path.exists():
                    return path
        return None

    def _is_original_st_pose(self, pose_dir: Path) -> bool:
        """
        Check if a pose directory contains original ST format (head-only faces).

        Original ST faces are head overlays that only occupy a portion of the canvas.
        Some characters pad their face images to match outfit canvas size, so we
        can't rely on canvas dimensions alone. Instead, we check how much of the
        canvas height the actual visible content occupies.

        Returns True if this is an original ST pose with head-only faces.
        """
        face_dir = pose_dir / "faces" / "face"
        if not face_dir.is_dir():
            return False

        # Check the first available face image
        for expr_num in ["0", "1"]:
            for ext in [".png", ".webp"]:
                face_path = face_dir / f"{expr_num}{ext}"
                if face_path.exists():
                    try:
                        with Image.open(face_path) as img:
                            img = img.convert("RGBA")
                            w, h = img.size

                            # Quick check: if clearly not tall, it's head-only
                            if h < w * 1.3:
                                return True

                            # Content-based check for padded face images:
                            # Threshold the alpha channel to ignore artifact pixels,
                            # then check what % of the canvas height has real content.
                            alpha = img.split()[3]
                            thresh = alpha.point(lambda p: 255 if p > 50 else 0)
                            bbox = thresh.getbbox()

                            if not bbox:
                                return False

                            content_height = bbox[3] - bbox[1]
                            # Head-only overlays typically fill <50% of canvas height.
                            # Full character sprites fill 70%+ of canvas height.
                            return content_height < h * 0.5
                    except Exception:
                        pass
        return False

    def _composite_outfit_face(self, outfit_path: Path, face_path: Path) -> Optional[Image.Image]:
        """
        Composite an outfit image with a face image (original ST format).

        In ST's system, both outfit and face are placed at position (0,0) on the same
        canvas. The outfit has a transparent head area, and the face fills it in.

        Returns the composited PIL Image, or None on error.
        """
        try:
            outfit = Image.open(outfit_path).convert("RGBA")
            face = Image.open(face_path).convert("RGBA")

            # Create canvas same size as outfit
            canvas = Image.new("RGBA", outfit.size, (0, 0, 0, 0))

            # Paste outfit at (0,0)
            canvas.paste(outfit, (0, 0), outfit)

            # Paste face at (0,0) - face is designed to align with outfit's head area
            canvas.paste(face, (0, 0), face)

            return canvas
        except Exception as e:
            print(f"[ERROR] Failed to composite {outfit_path} + {face_path}: {e}")
            return None

    def _generate_composite_contenders(self, pose_dir: Path, pose_letter: str) -> list:
        """
        Generate composite images for an original ST pose.

        Creates outfit+face composites, cycling through faces for each outfit
        to maximize variance. Face numbering restarts at 0 for each new pose.

        Args:
            pose_dir: Path to the pose directory (e.g., char_folder/a)
            pose_letter: The pose letter (e.g., "a")

        Returns:
            List of (label, temp_path) tuples for each composite contender.
        """
        import tempfile

        contenders = []

        outfits_dir = pose_dir / "outfits"
        faces_dir = pose_dir / "faces" / "face"

        if not outfits_dir.is_dir() or not faces_dir.is_dir():
            return contenders

        # Get list of outfits (sorted alphabetically)
        # Supports both flat files (outfits/casual.webp) and ST subdirectories
        # (outfits/casual/casual.webp) where the main image matches the folder name
        outfits = []
        for item in sorted(outfits_dir.iterdir()):
            if item.is_file() and item.suffix.lower() in [".png", ".webp"]:
                outfits.append(item)
            elif item.is_dir():
                # ST format: outfit subdir contains <name>.<ext> as the main image
                for ext in [".webp", ".png"]:
                    candidate = item / f"{item.name}{ext}"
                    if candidate.exists():
                        outfits.append(candidate)
                        break

        # Get list of numeric faces (sorted by number)
        faces = sorted([
            f for f in faces_dir.iterdir()
            if f.suffix.lower() in [".png", ".webp"] and f.stem.isdigit()
        ], key=lambda f: int(f.stem))

        if not outfits or not faces:
            return contenders

        # Create temp dir for composites
        temp_dir = Path(tempfile.gettempdir()) / "sprite_creator" / "composites"
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Generate composites: cycle through faces for each outfit
        face_idx = 0
        for outfit_path in outfits:
            outfit_name = outfit_path.stem  # e.g., "casual", "uniform"
            face_path = faces[face_idx % len(faces)]  # Cycle through faces
            face_num = face_path.stem

            # Create composite
            composite = self._composite_outfit_face(outfit_path, face_path)
            if composite is None:
                continue

            # Save to temp file
            temp_path = temp_dir / f"{pose_letter}_{outfit_name}_{face_num}.png"
            composite.save(temp_path, format="PNG")

            # Label like "A - Casual (0)"
            label = f"{pose_letter.upper()} - {outfit_name.title()} ({face_num})"
            contenders.append((label, temp_path))

            face_idx += 1

        return contenders

    def _load_first_available_sprite(self) -> None:
        """Load the first available sprite as the default selection.

        Priority: backup images > pose faces/composites > base.png
        """
        if not self.state.existing_character_folder:
            return

        char_folder = self.state.existing_character_folder
        loaded = False

        # Try backup image first (highest quality)
        backup_id = self.state.backup_id
        if backup_id and not loaded:
            backup_dir = get_backup_dir(backup_id)
            if backup_dir.is_dir():
                poses = sorted(self.state.existing_poses if isinstance(self.state.existing_poses, list) else list(self.state.existing_poses.keys()))
                for pose_letter in poses:
                    backup_face = backup_dir / pose_letter / "faces" / "face" / "0.png"
                    if backup_face.exists():
                        try:
                            self._selected_sprite_image = Image.open(backup_face).convert("RGBA")
                            self._display_sprite_preview()
                            loaded = True
                            break
                        except Exception:
                            pass

        # Try first pose from character folder
        if not loaded:
            poses = self.state.existing_poses if isinstance(self.state.existing_poses, list) else list(self.state.existing_poses.keys())
            if poses:
                pose_letter = sorted(poses)[0]
                pose_dir = char_folder / pose_letter

                if self._is_original_st_pose(pose_dir):
                    contenders = self._generate_composite_contenders(pose_dir, pose_letter)
                    if contenders:
                        label, temp_path = contenders[0]
                        try:
                            self._selected_sprite_image = Image.open(temp_path).convert("RGBA")
                            self._display_sprite_preview()
                            loaded = True
                        except Exception:
                            pass
                else:
                    sprite_path = self._get_sprite_path_for_pose(pose_dir)
                    if sprite_path:
                        try:
                            self._selected_sprite_image = Image.open(sprite_path).convert("RGBA")
                            self._display_sprite_preview()
                            loaded = True
                        except Exception:
                            pass

        # Last resort: original.png (or legacy base.png)
        if not loaded:
            base_path = char_folder / "original.png"
            if not base_path.exists():
                base_path = char_folder / "base.png"  # Legacy fallback
            if base_path.exists():
                try:
                    self._selected_sprite_image = Image.open(base_path).convert("RGBA")
                    self._display_sprite_preview()
                    loaded = True
                except Exception:
                    pass

        # Enable Normalize button if a sprite was loaded
        if loaded and self._normalize_btn:
            self._normalize_btn.configure(state="normal")

    def _on_sprite_card_click(self, image_path: Path) -> None:
        """Handle clicking on a sprite card."""
        try:
            self._selected_sprite_image = Image.open(image_path).convert("RGBA")
            self._display_sprite_preview()
            self._sprite_accepted = False  # Reset acceptance when selection changes
            # Reset normalization state
            self._normalized_sprite_image = None
            if self._normalized_preview_canvas:
                self._normalized_preview_canvas.delete("all")
            self._normalized_preview_tk_img = None
            # Enable Normalize button, disable Regenerate/Accept
            if self._normalize_btn:
                self._normalize_btn.configure(state="normal")
            if self._normalize_regen_btn:
                self._normalize_regen_btn.configure(state="disabled")
            if self._normalize_accept_btn:
                self._normalize_accept_btn.configure(state="disabled")
            self._update_next_button_state()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load image:\n{e}")

    def _display_sprite_preview(self) -> None:
        """Display the selected sprite in the left preview canvas."""
        if self._selected_sprite_image is None:
            return

        # Clear canvas
        self._sprite_preview_canvas.delete("all")

        # Calculate display size (fit within canvas)
        img = self._selected_sprite_image
        canvas_w, canvas_h = 340, 500

        # Calculate scale to fit
        scale_w = canvas_w / img.width
        scale_h = canvas_h / img.height
        scale = min(scale_w, scale_h, 1.0)  # Don't upscale

        disp_w = int(img.width * scale)
        disp_h = int(img.height * scale)

        # Resize for display
        display_img = img.resize((disp_w, disp_h), Image.Resampling.LANCZOS)
        self._sprite_preview_tk_img = ImageTk.PhotoImage(display_img)

        # Center horizontally, anchor to bottom (sprites stand on ground)
        x = (canvas_w - disp_w) // 2
        y = canvas_h - disp_h  # Anchor to bottom
        self._sprite_preview_canvas.create_image(x, y, image=self._sprite_preview_tk_img, anchor="nw")

    def _display_normalized_preview(self) -> None:
        """Display the normalized sprite in the right preview canvas."""
        if self._normalized_sprite_image is None or self._normalized_preview_canvas is None:
            return

        # Clear canvas
        self._normalized_preview_canvas.delete("all")

        # Calculate display size (fit within canvas)
        img = self._normalized_sprite_image
        canvas_w, canvas_h = 340, 500

        scale_w = canvas_w / img.width
        scale_h = canvas_h / img.height
        scale = min(scale_w, scale_h, 1.0)

        disp_w = int(img.width * scale)
        disp_h = int(img.height * scale)

        display_img = img.resize((disp_w, disp_h), Image.Resampling.LANCZOS)
        self._normalized_preview_tk_img = ImageTk.PhotoImage(display_img)

        x = (canvas_w - disp_w) // 2
        y = canvas_h - disp_h
        self._normalized_preview_canvas.create_image(x, y, image=self._normalized_preview_tk_img, anchor="nw")

    def _on_normalize_click(self) -> None:
        """Handle clicking the Normalize button."""
        if self._selected_sprite_image is None:
            messagebox.showerror("No Selection", "Please select a sprite first.")
            return

        if self._is_normalizing_add_existing:
            return

        # Disable buttons during normalization
        self._normalize_btn.configure(state="disabled")
        self._normalize_regen_btn.configure(state="disabled")
        self._normalize_accept_btn.configure(state="disabled")

        # Show loading overlay on the right canvas
        self._show_normalize_loading()

        # Run normalization in background thread
        self._is_normalizing_add_existing = True
        thread = threading.Thread(target=self._run_add_existing_normalization, daemon=True)
        thread.start()

    def _on_regenerate_click(self) -> None:
        """Handle clicking the Regenerate button (re-run normalization)."""
        self._on_normalize_click()

    def _show_normalize_loading(self) -> None:
        """Show loading overlay on the normalized preview canvas."""
        if self._normalized_preview_frame is None:
            return

        self._hide_normalize_loading()

        self._normalize_loading_overlay = tk.Frame(self._normalized_preview_frame, bg=OVERLAY_BG)
        self._normalize_loading_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)

        tk.Label(
            self._normalize_loading_overlay,
            text="Normalizing\nimage...",
            bg=OVERLAY_BG,
            fg=TEXT_COLOR,
            font=BODY_FONT,
        ).place(relx=0.5, rely=0.5, anchor="center")

    def _hide_normalize_loading(self) -> None:
        """Hide the normalization loading overlay."""
        if self._normalize_loading_overlay is not None:
            try:
                self._normalize_loading_overlay.destroy()
            except tk.TclError:
                pass
            self._normalize_loading_overlay = None

    def _run_add_existing_normalization(self) -> None:
        """Run Gemini normalization on the selected sprite (background thread)."""
        try:
            from ...api.gemini_client import get_api_key, call_gemini_image_edit, load_image_as_base64
            from ...api.prompt_builders import build_normalize_existing_character_prompt

            api_key = self.state.api_key or get_api_key(use_gui=True)

            # Save selected image to temp file for base64 encoding
            import tempfile
            temp_dir = Path(tempfile.gettempdir()) / "sprite_creator"
            temp_dir.mkdir(exist_ok=True)
            temp_path = temp_dir / f"normalize_input_{id(self)}.png"
            self._selected_sprite_image.save(temp_path, format="PNG")

            from ...config import load_background_color
            image_b64 = load_image_as_base64(str(temp_path))
            prompt = build_normalize_existing_character_prompt(background_color=load_background_color())

            result_bytes = call_gemini_image_edit(
                api_key=api_key,
                prompt=prompt,
                image_b64=image_b64,
                skip_background_removal=True,
            )

            if result_bytes:
                normalized = Image.open(BytesIO(result_bytes)).convert("RGBA")
                self.schedule_callback(lambda: self._on_normalize_complete(normalized))
            else:
                self.schedule_callback(lambda: self._on_normalize_error("No image returned from API"))

        except Exception as e:
            self.schedule_callback(lambda: self._on_normalize_error(str(e)))

    def _on_normalize_complete(self, normalized_image: Image.Image) -> None:
        """Handle successful normalization (main thread)."""
        self._is_normalizing_add_existing = False
        self._hide_normalize_loading()

        self._normalized_sprite_image = normalized_image
        self._display_normalized_preview()

        # Enable Regenerate and Accept buttons
        self._normalize_regen_btn.configure(state="normal")
        self._normalize_accept_btn.configure(state="normal")
        # Re-enable Normalize button for convenience
        self._normalize_btn.configure(state="normal")

    def _on_normalize_error(self, error: str) -> None:
        """Handle normalization error (main thread)."""
        self._is_normalizing_add_existing = False
        self._hide_normalize_loading()

        # Show a popup for quota/billing errors so the user clearly sees it
        if "quota" in error.lower() or "free_tier" in error.lower() or "billing" in error.lower():
            messagebox.showerror("API Quota Exceeded", error)
        else:
            messagebox.showerror("Normalization Failed", f"Failed to normalize image:\n\n{error[:200]}")

        # Also show brief error on the canvas
        if self._normalized_preview_canvas:
            self._normalized_preview_canvas.delete("all")
            brief = error.split("\n")[0][:60]
            self._normalized_preview_canvas.create_text(
                110, 170,
                text=f"{brief}\n\nClick Normalize to retry.",
                fill="#ff6666",
                font=SMALL_FONT,
                width=200,
                justify="center",
            )

        # Re-enable Normalize button so user can retry
        self._normalize_btn.configure(state="normal")
        self._normalize_regen_btn.configure(state="normal")

    def _on_accept_sprite_selection(self) -> None:
        """Handle accepting the normalized sprite."""
        if self._normalized_sprite_image is None:
            messagebox.showerror("No Normalized Image", "Please normalize the sprite first.")
            return

        # Store the NORMALIZED sprite in state
        self.state.selected_base_sprite = self._normalized_sprite_image.copy()
        self._sprite_accepted = True

        # Also set as source image for generation compatibility
        self.state.source_image = self._normalized_sprite_image.copy()

        # Save normalized image to temp file for generation steps
        import tempfile
        temp_dir = Path(tempfile.gettempdir()) / "sprite_creator"
        temp_dir.mkdir(exist_ok=True)
        temp_path = temp_dir / f"selected_base_{id(self)}.png"
        self._normalized_sprite_image.save(temp_path, format="PNG")
        self.state.cropped_image_path = temp_path
        # Reset base_pose_path so the review step picks up the new selection
        self.state.base_pose_path = None
        # Mark as already normalized — sprite selector images go through Gemini
        # normalization already, so skip the post-crop normalize in outfit generation.
        self.state.base_pose_normalized_post_crop = True

        # Update button states
        self._update_next_button_state()

        # Visual feedback
        self._normalize_accept_btn.configure(text="Accepted", state="disabled")
        self._normalize_btn.configure(state="disabled")
        self._normalize_regen_btn.configure(state="disabled")


# =============================================================================
# Step 3: Generation Options
# =============================================================================

class OptionsStep(WizardStep):
    """Step 4: Select outfits and expressions to generate."""

    STEP_ID = "options"
    STEP_TITLE = "Options"
    STEP_NUMBER = 4
    STEP_TIP = (
        "Pick which outfits and expressions to generate. "
        "You can also save and load custom outfit presets."
    )
    STEP_HELP = """Generation Options

This step selects which outfits and expressions to generate.

INCLUDE BASE IMAGE AS OUTFIT?
Choose whether your original character image (with its current outfit) should be included as one of the final outfits.
- Yes: The base image becomes the "Original" outfit
- No: Only generated outfits are included

OUTFITS (Left Column)
Check the box next to each outfit type you want to generate.

Available types: Casual, Formal, Athletic, Swimsuit, Underwear, Uniform

For each outfit, choose a generation mode:

Random Mode
The AI generates a unique outfit description based on the character's archetype. Each generation produces different results.

Custom Mode
You write the outfit description. A text box appears where you can describe exactly what you want (e.g., "red sundress with white polka dots").

ST Uniform Mode (Uniform only)
Only available for Young Woman/Man archetypes. Uses reference images to generate a consistent school uniform style across all characters.

Note: Underwear uses a tiered fallback system due to content filtering. If one description is blocked, the system tries progressively safer alternatives.

CUSTOM OUTFITS
Click "+ Add Custom Outfit" to create additional outfit types with your own name and description. Maximum 15 total outfits.

EXPRESSIONS (Right Column)
Check which expressions to generate for each outfit. Expressions are grouped into categories:

Expression 0 (neutral) is always included as the base.

Core (1-7): Talking, Happy, Sad, Angry, Surprised, Embarrassed, Confused
Extended (8-12): Laughing, Scared, Crying, Skeptical, Pensive
Personality (13-14): Confident/Smug, Playful/Wink
Situational (15-16): Sleepy, Aroused

CUSTOM EXPRESSIONS
Click "+ Add Custom Expression" to add your own expressions with a description. The system auto-assigns the next available number.

PERFORMANCE NOTE
More outfits and expressions = longer generation time. Each outfit generates all selected expressions, so 6 outfits x 17 expressions = 102 images.

ADD-TO-EXISTING MODE
When adding to an existing character, an additional section appears:

ADD EXPRESSIONS TO EXISTING OUTFITS
(Only visible for Sprite Creator characters)
- Shows all existing outfits (pose letters) with their expressions
- Check an outfit to enable selecting expressions
- Blue chips = missing expressions (new generation)
- Orange chips = existing expressions (select to replace)
- Expression 0 (Neutral) cannot be replaced — it comes from the outfit image
- Quick actions ("Match Above", "Select All Missing") only select missing expressions

If you select any existing expressions for replacement, an overwrite
warning will appear. You must check the acknowledgment box before
proceeding. This is separate from the content filter warning.

You must select at least one option:
- One new outfit to generate, OR
- One existing outfit to add expressions to

Click Next when you've made your selections."""

    MAX_OUTFITS = 20
    MAX_EXPRESSIONS = 30

    # Expression category groupings
    EXPR_CATEGORIES = [
        ("Core", ["0", "1", "2", "3", "4", "5", "6", "7"]),
        ("Extended", ["8", "9", "10", "11", "12"]),
        ("Personality", ["13", "14"]),
        ("Situational", ["15", "16"]),
    ]

    # Risky settings that may be blocked by content filters
    RISKY_OUTFITS = {"underwear", "swimsuit"}
    RISKY_EXPRESSIONS = {"16"}  # aroused

    def __init__(self, wizard, state: WizardState):
        super().__init__(wizard, state)
        self._outfit_vars: Dict[str, tk.IntVar] = {}
        self._outfit_mode_vars: Dict[str, tk.StringVar] = {}
        self._outfit_entries: Dict[str, tk.Entry] = {}
        self._outfit_cards: Dict[str, tk.Frame] = {}  # outfit key -> card frame
        self._outfit_segments: Dict[str, 'SegmentedControl'] = {}  # outfit key -> segmented control
        self._expr_vars: Dict[str, tk.IntVar] = {}
        self._expr_chips: Dict[str, ToggleChip] = {}  # expr key -> chip widget
        self._uniform_card: Optional[tk.Frame] = None  # Track uniform card for hiding
        self._has_standard_uniform: bool = True  # ST Uniform always available for all archetypes

        # Base outfit option
        self._use_base_as_outfit_var: Optional[tk.IntVar] = None

        # Expression count label
        self._expr_count_label: Optional[tk.Label] = None

        # Custom outfit/expression tracking
        self._custom_outfits: List[Dict] = []  # [{frame, name_entry, desc_entry}]
        self._custom_expressions: List[Dict] = []  # [{frame, key_entry, desc_entry}]
        self._custom_outfits_frame: Optional[tk.Frame] = None
        self._custom_expressions_frame: Optional[tk.Frame] = None
        self._add_outfit_btn: Optional[tk.Button] = None
        self._add_expression_btn: Optional[tk.Button] = None
        self._outfit_scroll_frame: Optional[tk.Frame] = None
        self._outfit_canvas: Optional[tk.Canvas] = None
        self._expr_inner_frame: Optional[tk.Frame] = None
        self._expr_canvas: Optional[tk.Canvas] = None

        # Add-to-existing mode: expressions for existing outfits
        self._existing_outfits_section: Optional[tk.Frame] = None
        self._existing_outfit_vars: Dict[str, tk.IntVar] = {}  # pose_letter -> enabled var
        self._existing_expr_vars: Dict[str, Dict[str, tk.IntVar]] = {}  # pose_letter -> {expr_num: var}
        self._existing_expr_chips: Dict[str, Dict[str, ToggleChip]] = {}  # pose -> {expr: chip}
        self._existing_expressions_data: Dict[str, List[str]] = {}  # pose_letter -> [existing expr nums]

        # Content warning tracking
        self._content_warning_frame: Optional[tk.Frame] = None
        self._content_warning_var: Optional[tk.BooleanVar] = None
        self._content_warning_label: Optional[tk.Label] = None
        self._last_risky_set: set = set()

        # Overwrite warning tracking
        self._warnings_row: Optional[tk.Frame] = None
        self._overwrite_warning_frame: Optional[tk.Frame] = None
        self._overwrite_warning_var: Optional[tk.BooleanVar] = None
        self._overwrite_warning_label: Optional[tk.Label] = None
        self._last_overwrite_set: set = set()

    def build_ui(self, parent: tk.Frame) -> None:
        parent.configure(bg=BG_COLOR)

        # Title
        tk.Label(
            parent,
            text="Generation Options",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=PAGE_TITLE_FONT,
        ).pack(pady=(0, 8))

        self._build_tip_bar(parent)

        # --- Warnings Row (holds content warning + overwrite warning side by side) ---
        self._warnings_row = tk.Frame(parent, bg=BG_COLOR)
        # Don't pack yet — shown/hidden by _update_content_warning / _update_overwrite_warning

        # --- Content Warning Banner (left side) ---
        self._content_warning_var = tk.BooleanVar(value=False)
        self._content_warning_frame = tk.Frame(
            self._warnings_row, bg=CARD_BG, padx=12, pady=10,
            highlightbackground=WARNING_TEXT, highlightthickness=2,
        )

        warning_header = tk.Frame(self._content_warning_frame, bg=CARD_BG)
        warning_header.pack(fill="x")
        tk.Label(
            warning_header,
            text="Content Filter Warning",
            bg=CARD_BG, fg=WARNING_TEXT, font=SECTION_FONT,
        ).pack(side="left")

        self._content_warning_label = tk.Label(
            self._content_warning_frame,
            text="",
            bg=CARD_BG, fg=TEXT_COLOR, font=SMALL_FONT,
            justify="left", anchor="w", wraplength=400,
        )
        self._content_warning_label.pack(fill="x", pady=(6, 6))

        ack_frame = tk.Frame(self._content_warning_frame, bg=CARD_BG)
        ack_frame.pack(fill="x")
        tk.Checkbutton(
            ack_frame,
            text="I understand these may not generate successfully",
            variable=self._content_warning_var,
            bg=CARD_BG, fg=TEXT_COLOR, selectcolor="#1E1E1E",
            activebackground=CARD_BG, activeforeground=TEXT_COLOR,
            font=SMALL_FONT,
        ).pack(side="left")

        # --- Overwrite Warning Banner (right side) ---
        self._overwrite_warning_var = tk.BooleanVar(value=False)
        self._last_overwrite_set: set = set()
        self._overwrite_warning_frame = tk.Frame(
            self._warnings_row, bg=CARD_BG, padx=12, pady=10,
            highlightbackground=DANGER_COLOR, highlightthickness=2,
        )

        overwrite_header = tk.Frame(self._overwrite_warning_frame, bg=CARD_BG)
        overwrite_header.pack(fill="x")
        tk.Label(
            overwrite_header,
            text="Expression Overwrite Warning",
            bg=CARD_BG, fg=DANGER_COLOR, font=SECTION_FONT,
        ).pack(side="left")

        self._overwrite_warning_label = tk.Label(
            self._overwrite_warning_frame,
            text="",
            bg=CARD_BG, fg=TEXT_COLOR, font=SMALL_FONT,
            justify="left", anchor="w", wraplength=400,
        )
        self._overwrite_warning_label.pack(fill="x", pady=(6, 6))

        overwrite_ack_frame = tk.Frame(self._overwrite_warning_frame, bg=CARD_BG)
        overwrite_ack_frame.pack(fill="x")
        tk.Checkbutton(
            overwrite_ack_frame,
            text="I understand these existing expressions will be replaced",
            variable=self._overwrite_warning_var,
            bg=CARD_BG, fg=TEXT_COLOR, selectcolor="#1E1E1E",
            activebackground=CARD_BG, activeforeground=TEXT_COLOR,
            font=SMALL_FONT,
        ).pack(side="left")

        # Two-column layout
        self._columns_frame = tk.Frame(parent, bg=BG_COLOR)
        self._columns_frame.pack(fill="both", expand=True)
        columns = self._columns_frame

        # ================================================================
        # LEFT COLUMN: Outfits
        # ================================================================
        left_col = tk.Frame(columns, bg=BG_COLOR)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 10))

        # --- Base Image as Outfit toggle ---
        self._base_outfit_frame = tk.Frame(left_col, bg=CARD_BG, padx=12, pady=10,
                                           highlightbackground=ACCENT_COLOR, highlightthickness=2)
        self._base_outfit_frame.pack(fill="x", pady=(0, 12))
        base_outfit_frame = self._base_outfit_frame

        base_header = tk.Frame(base_outfit_frame, bg=CARD_BG)
        base_header.pack(fill="x")

        tk.Label(
            base_header,
            text="Include Original Image as Outfit",
            bg=CARD_BG,
            fg=ACCENT_COLOR,
            font=SECTION_FONT,
        ).pack(side="left")

        # Toggle button for base outfit (replaces radio buttons)
        self._use_base_as_outfit_var = tk.IntVar(value=1)
        self._base_toggle_btn = tk.Button(
            base_header,
            text="ON",
            command=self._toggle_base_outfit,
            bg=ACCENT_COLOR,
            fg=TEXT_COLOR,
            activebackground=ACCENT_COLOR,
            activeforeground=TEXT_COLOR,
            font=SMALL_FONT_BOLD,
            relief="flat",
            cursor="hand2",
            bd=0,
            padx=12,
            pady=2,
            width=5,
        )
        self._base_toggle_btn.pack(side="right")

        tk.Label(
            base_outfit_frame,
            text="Uses the base character image as the 'Original' outfit",
            bg=CARD_BG,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        ).pack(anchor="w", pady=(4, 0))

        # --- Outfits header ---
        tk.Label(
            left_col,
            text="Outfits",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=SECTION_FONT,
        ).pack(anchor="w", pady=(0, 4))

        tk.Label(
            left_col,
            text="Click to select, choose generation mode per outfit",
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        ).pack(anchor="w", pady=(0, 8))

        # --- Outfit cards (scrollable) ---
        outfit_scroll_container = tk.Frame(left_col, bg=BG_COLOR)
        outfit_scroll_container.pack(fill="both", expand=True)

        self._outfit_canvas = tk.Canvas(
            outfit_scroll_container, bg=BG_COLOR, highlightthickness=0
        )
        outfit_scrollbar = ttk.Scrollbar(
            outfit_scroll_container, orient="vertical", command=self._outfit_canvas.yview
        )
        self._outfit_canvas.configure(yscrollcommand=outfit_scrollbar.set)

        outfit_scrollbar.pack(side="right", fill="y")
        self._outfit_canvas.pack(side="left", fill="both", expand=True)

        self._outfit_scroll_frame = tk.Frame(self._outfit_canvas, bg=BG_COLOR)
        self._outfit_canvas.create_window(
            (0, 0), window=self._outfit_scroll_frame, anchor="nw"
        )
        self._outfit_scroll_frame.bind(
            "<Configure>",
            lambda e: self._outfit_canvas.configure(
                scrollregion=self._outfit_canvas.bbox("all")
            )
        )

        for key in ALL_OUTFIT_KEYS:
            self._build_outfit_card(self._outfit_scroll_frame, key)

        # Container for custom outfits
        self._custom_outfits_frame = tk.Frame(self._outfit_scroll_frame, bg=BG_COLOR)
        self._custom_outfits_frame.pack(fill="x", pady=(8, 0))

        # Button row: Add Custom + Saved Outfits
        outfit_btn_row = tk.Frame(self._outfit_scroll_frame, bg=BG_COLOR)
        outfit_btn_row.pack(anchor="w", pady=(8, 0))

        self._add_outfit_btn = create_secondary_button(
            outfit_btn_row,
            "+ Add Custom Outfit",
            self._add_custom_outfit,
            width=18,
        )
        self._add_outfit_btn.pack(side="left", padx=(0, 8))

        create_secondary_button(
            outfit_btn_row,
            "Saved Outfits",
            self._open_saved_outfits_dialog,
            width=14,
        ).pack(side="left")

        # ================================================================
        # RIGHT COLUMN: Expressions
        # ================================================================
        right_col = tk.Frame(columns, bg=BG_COLOR)
        right_col.pack(side="left", fill="both", expand=True, padx=(10, 0))

        # Header with count
        expr_header = tk.Frame(right_col, bg=BG_COLOR)
        expr_header.pack(fill="x", pady=(0, 4))

        tk.Label(
            expr_header,
            text="Expressions",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=SECTION_FONT,
        ).pack(side="left")

        self._expr_count_label = tk.Label(
            expr_header,
            text="",
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        )
        self._expr_count_label.pack(side="right")

        # Quick action buttons
        quick_actions = tk.Frame(right_col, bg=BG_COLOR)
        quick_actions.pack(fill="x", pady=(0, 8))

        create_secondary_button(
            quick_actions, "Select All", self._expr_select_all, width=9
        ).pack(side="left", padx=(0, 4))
        create_secondary_button(
            quick_actions, "Deselect All", self._expr_deselect_all, width=10
        ).pack(side="left", padx=(0, 4))
        create_secondary_button(
            quick_actions, "Core Only", self._expr_core_only, width=9
        ).pack(side="left")

        # Expression chips grouped by category (scrollable)
        self._expr_canvas = tk.Canvas(right_col, bg=BG_COLOR, highlightthickness=0, height=300)
        expr_scrollbar = ttk.Scrollbar(right_col, orient="vertical", command=self._expr_canvas.yview)
        expr_inner = tk.Frame(self._expr_canvas, bg=BG_COLOR)

        expr_inner.bind(
            "<Configure>",
            lambda e: self._expr_canvas.configure(scrollregion=self._expr_canvas.bbox("all"))
        )
        self._expr_canvas.create_window((0, 0), window=expr_inner, anchor="nw")
        self._expr_canvas.configure(yscrollcommand=expr_scrollbar.set)

        self._expr_canvas.pack(side="left", fill="both", expand=True)
        expr_scrollbar.pack(side="right", fill="y")

        self._expr_inner_frame = expr_inner

        # Build expression lookup for short display names
        expr_lookup = {k: d for k, d in EXPRESSIONS_SEQUENCE}

        # Expression short display names (for chips)
        expr_short_names = {
            "0": "Neutral", "1": "Talking", "2": "Happy", "3": "Sad",
            "4": "Angry", "5": "Surprised", "6": "Embarrassed", "7": "Confused",
            "8": "Laughing", "9": "Scared", "10": "Crying", "11": "Skeptical",
            "12": "Pensive", "13": "Confident", "14": "Playful",
            "15": "Sleepy", "16": "Aroused",
        }

        for cat_name, cat_keys in self.EXPR_CATEGORIES:
            # Category label
            tk.Label(
                expr_inner,
                text=cat_name,
                bg=BG_COLOR,
                fg=TEXT_SECONDARY,
                font=SMALL_FONT_BOLD,
            ).pack(anchor="w", pady=(8, 4))

            # Chip grid for this category
            chip_row = tk.Frame(expr_inner, bg=BG_COLOR)
            chip_row.pack(fill="x", pady=(0, 4))

            for i, key in enumerate(cat_keys):
                short = expr_short_names.get(key, key)
                chip_text = f"{key} - {short}"

                if key == "0":
                    # Neutral is always included - show as non-interactive filled chip
                    chip = FilledChip(chip_row, f"{chip_text} (always)")
                    chip.grid(row=i // 4, column=i % 4, padx=3, pady=3, sticky="w")
                else:
                    var = tk.IntVar(value=1)
                    self._expr_vars[key] = var

                    def make_toggle(v=var):
                        def on_toggle(selected):
                            v.set(1 if selected else 0)
                            self._update_expr_count()
                            self._update_content_warning()
                        return on_toggle

                    chip = create_toggle_chip(
                        chip_row,
                        chip_text,
                        selected=True,
                        on_toggle=make_toggle(),
                    )
                    chip.grid(row=i // 4, column=i % 4, padx=3, pady=3, sticky="w")
                    self._expr_chips[key] = chip

        # Container for custom expressions
        self._custom_expressions_frame = tk.Frame(expr_inner, bg=BG_COLOR)
        self._custom_expressions_frame.pack(fill="x", pady=(8, 0))

        # Add custom expression button
        self._add_expression_btn = create_secondary_button(
            expr_inner,
            "+ Add Custom Expression",
            self._add_custom_expression,
            width=20,
        )
        self._add_expression_btn.pack(anchor="w", pady=(8, 0))

        # Initial count
        self._update_expr_count()

        # ================================================================
        # ADD-TO-EXISTING MODE: Expressions for Existing Outfits
        # ================================================================
        self._existing_outfits_section = tk.Frame(parent, bg=BG_COLOR)

        # Section header
        tk.Label(
            self._existing_outfits_section,
            text="Add Expressions to Existing Outfits",
            bg=BG_COLOR,
            fg=ACCENT_COLOR,
            font=SECTION_FONT,
        ).pack(anchor="w", pady=(16, 2))

        tk.Label(
            self._existing_outfits_section,
            text="(separate from the new outfit expressions above)",
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        ).pack(anchor="w", pady=(0, 8))

        # Quick actions for existing outfits
        self._existing_quick_actions = tk.Frame(self._existing_outfits_section, bg=BG_COLOR)
        self._existing_quick_actions.pack(fill="x", pady=(0, 8))

        create_secondary_button(
            self._existing_quick_actions, "Match Above",
            self._existing_match_new_outfits, width=12
        ).pack(side="left", padx=(0, 4))
        create_secondary_button(
            self._existing_quick_actions, "Select All Missing",
            self._existing_select_all_missing, width=16
        ).pack(side="left")

        # Color legend for expression chips
        legend_frame = tk.Frame(self._existing_outfits_section, bg=BG_COLOR)
        legend_frame.pack(fill="x", pady=(0, 6))
        tk.Label(
            legend_frame, text="\u25CF", bg=BG_COLOR, fg=ACCENT_COLOR, font=SMALL_FONT,
        ).pack(side="left")
        tk.Label(
            legend_frame, text="New expression", bg=BG_COLOR, fg=TEXT_SECONDARY, font=SMALL_FONT,
        ).pack(side="left", padx=(2, 12))
        tk.Label(
            legend_frame, text="\u25CF", bg=BG_COLOR, fg=WARNING_TEXT, font=SMALL_FONT,
        ).pack(side="left")
        tk.Label(
            legend_frame, text="Existing (will replace if selected)", bg=BG_COLOR, fg=TEXT_SECONDARY, font=SMALL_FONT,
        ).pack(side="left", padx=(2, 0))

        # Scrollable container for existing poses
        scroll_container = tk.Frame(self._existing_outfits_section, bg=BG_COLOR)
        scroll_container.pack(fill="both", expand=True)

        self._existing_poses_canvas = tk.Canvas(
            scroll_container, bg=BG_COLOR, highlightthickness=0, height=350
        )
        scrollbar = ttk.Scrollbar(
            scroll_container, orient="vertical", command=self._existing_poses_canvas.yview
        )
        self._existing_poses_canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self._existing_poses_canvas.pack(side="left", fill="both", expand=True)

        self._existing_poses_content = tk.Frame(self._existing_poses_canvas, bg=BG_COLOR)
        self._existing_poses_canvas.create_window(
            (0, 0), window=self._existing_poses_content, anchor="nw"
        )

        self._existing_poses_content.bind(
            "<Configure>",
            lambda e: self._existing_poses_canvas.configure(
                scrollregion=self._existing_poses_canvas.bbox("all")
            )
        )

    def _bind_mousewheel_to_canvas(self, widget: tk.Widget, canvas: tk.Canvas) -> None:
        """Bind mouse wheel scrolling to a widget and all its descendants for a canvas."""
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        widget.bind("<MouseWheel>", on_mousewheel)
        for child in widget.winfo_children():
            self._bind_mousewheel_to_canvas(child, canvas)

    def _toggle_base_outfit(self) -> None:
        """Toggle the base outfit on/off."""
        current = self._use_base_as_outfit_var.get()
        new_val = 0 if current else 1
        self._use_base_as_outfit_var.set(new_val)
        if new_val:
            self._base_toggle_btn.configure(text="ON", bg=ACCENT_COLOR)
            self._base_toggle_btn.bind("<Enter>", lambda e: self._base_toggle_btn.configure(bg=ACCENT_HOVER))
            self._base_toggle_btn.bind("<Leave>", lambda e: self._base_toggle_btn.configure(bg=ACCENT_COLOR))
        else:
            self._base_toggle_btn.configure(text="OFF", bg="#555555")
            self._base_toggle_btn.bind("<Enter>", lambda e: self._base_toggle_btn.configure(bg="#666666"))
            self._base_toggle_btn.bind("<Leave>", lambda e: self._base_toggle_btn.configure(bg="#555555"))

    def _update_expr_count(self) -> None:
        """Update the expression count label."""
        selected = 1  # Neutral always included
        selected += sum(1 for v in self._expr_vars.values() if v.get() == 1)
        total = 1 + len(self._expr_vars) + len(self._custom_expressions)
        if self._expr_count_label:
            self._expr_count_label.configure(text=f"{selected} of {total} selected")

    def _expr_select_all(self) -> None:
        """Select all expression chips."""
        for key, chip in self._expr_chips.items():
            chip.selected = True
            self._expr_vars[key].set(1)
        self._update_expr_count()
        self._update_content_warning()

    def _expr_deselect_all(self) -> None:
        """Deselect all expression chips."""
        for key, chip in self._expr_chips.items():
            chip.selected = False
            self._expr_vars[key].set(0)
        self._update_expr_count()
        self._update_content_warning()

    def _expr_core_only(self) -> None:
        """Select only core expressions (1-7)."""
        core_keys = set(self.EXPR_CATEGORIES[0][1]) - {"0"}  # Core minus neutral
        for key, chip in self._expr_chips.items():
            is_core = key in core_keys
            chip.selected = is_core
            self._expr_vars[key].set(1 if is_core else 0)
        self._update_expr_count()
        self._update_content_warning()

    def _build_outfit_card(self, parent: tk.Frame, key: str) -> None:
        """Build a single outfit card with toggle and segmented mode control."""
        is_default = key in OUTFIT_KEYS

        # Card frame
        card = tk.Frame(parent, bg=CARD_BG, padx=10, pady=8,
                        highlightbackground=ACCENT_COLOR if is_default else BORDER_COLOR,
                        highlightthickness=2 if is_default else 1)
        card.pack(fill="x", pady=(0, 4))
        self._outfit_cards[key] = card

        if key == "uniform":
            self._uniform_card = card

        # Checkbox variable
        var = tk.IntVar(value=1 if is_default else 0)
        self._outfit_vars[key] = var

        # Top row: outfit name toggle + mode segmented control
        top_row = tk.Frame(card, bg=CARD_BG)
        top_row.pack(fill="x")

        # Outfit name as clickable toggle button
        toggle_btn = tk.Button(
            top_row,
            text=key.capitalize(),
            command=lambda k=key: self._toggle_outfit(k),
            bg=ACCENT_COLOR if is_default else "#555555",
            fg=TEXT_COLOR,
            activebackground=ACCENT_COLOR,
            activeforeground=TEXT_COLOR,
            font=SMALL_FONT_BOLD,
            relief="flat",
            cursor="hand2",
            bd=0,
            padx=10,
            pady=2,
            anchor="w",
        )
        toggle_btn.pack(side="left", padx=(0, 12))
        # Store toggle button reference for updates
        card._toggle_btn = toggle_btn

        # Mode selection: segmented control
        mode_var = tk.StringVar(value="random")
        self._outfit_mode_vars[key] = mode_var

        mode_options = ["Random", "Custom"]
        if key == "uniform":
            mode_options.append("ST Uniform")

        def make_mode_change(k=key, m=mode_var):
            def on_change(selected):
                mode_map = {"Random": "random", "Custom": "custom", "ST Uniform": "standard_uniform"}
                m.set(mode_map.get(selected, "random"))
                self._update_outfit_entry_visibility(k)
            return on_change

        segment = create_segmented_control(
            top_row,
            mode_options,
            default="Random",
            on_change=make_mode_change(),
        )
        segment.pack(side="right")
        self._outfit_segments[key] = segment

        # Custom prompt entry (hidden by default, shown when Custom mode selected)
        entry = tk.Entry(
            card,
            width=40,
            bg="#1E1E1E",
            fg=TEXT_COLOR,
            insertbackground=TEXT_COLOR,
            font=SMALL_FONT,
        )
        self._outfit_entries[key] = entry
        # Don't pack - will be shown/hidden based on mode

        # Update card appearance based on toggle
        def update_card_appearance(*args):
            selected = var.get() == 1
            card.configure(
                highlightbackground=ACCENT_COLOR if selected else BORDER_COLOR,
                highlightthickness=2 if selected else 1,
            )
            toggle_btn.configure(bg=ACCENT_COLOR if selected else "#555555")

        var.trace_add("write", update_card_appearance)

    def _toggle_outfit(self, key: str) -> None:
        """Toggle an outfit on/off."""
        var = self._outfit_vars[key]
        var.set(0 if var.get() else 1)
        self._update_outfit_entry_visibility(key)
        self._update_content_warning()

    def _update_outfit_entry_visibility(self, key: str) -> None:
        """Show/hide custom prompt entry based on mode and selection."""
        var = self._outfit_vars[key]
        mode_var = self._outfit_mode_vars[key]
        entry = self._outfit_entries[key]

        if var.get() == 1 and mode_var.get() == "custom":
            entry.pack(fill="x", pady=(6, 0))
        else:
            entry.pack_forget()

    def _get_total_outfit_count(self) -> int:
        """Get total number of selected + custom outfits."""
        selected = sum(1 for v in self._outfit_vars.values() if v.get() == 1)
        return selected + len(self._custom_outfits)

    def _get_total_expression_count(self) -> int:
        """Get total number of selected + custom expressions."""
        selected = 1  # Neutral is always included
        selected += sum(1 for v in self._expr_vars.values() if v.get() == 1)
        return selected + len(self._custom_expressions)

    def _get_risky_settings(self) -> Dict[str, str]:
        """Return dict of currently selected risky settings with descriptions."""
        risky = {}
        for key in ALL_OUTFIT_KEYS:
            if key in self.RISKY_OUTFITS and self._outfit_vars.get(key, tk.IntVar(value=0)).get() == 1:
                if key == "underwear":
                    risky[key] = "Underwear - frequently blocked, uses tiered fallback prompts"
                elif key == "swimsuit":
                    risky[key] = "Swimsuit - occasionally blocked by content filters"
        for key in self.RISKY_EXPRESSIONS:
            if self._expr_vars.get(key, tk.IntVar(value=0)).get() == 1:
                risky[f"expr_{key}"] = "Aroused (Expression 16) - may be refused by content filters"
        return risky

    def _update_warnings_row(self) -> None:
        """Show/hide the warnings row based on whether any warning is active."""
        # Use state flags instead of winfo_ismapped() — children packed inside
        # an unmapped parent report as unmapped, causing a chicken-and-egg issue.
        has_content = bool(self._last_risky_set)
        has_overwrite = bool(self._last_overwrite_set)

        if has_content or has_overwrite:
            if not self._warnings_row.winfo_ismapped():
                self._warnings_row.pack(fill="x", pady=(0, 12), before=self._columns_frame)
        else:
            self._warnings_row.pack_forget()

    def _update_content_warning(self) -> None:
        """Show/hide the content warning banner based on current risky selections."""
        if not self._content_warning_frame:
            return

        risky = self._get_risky_settings()
        risky_set = set(risky.keys())

        if risky_set:
            # Build warning text
            lines = ["Some of your selections may be blocked by Gemini's safety filters:\n"]
            for desc in risky.values():
                lines.append(f"  \u2022 {desc}")
            self._content_warning_label.configure(text="\n".join(lines))

            # If risky set changed, reset acknowledgment
            if risky_set != self._last_risky_set:
                self._content_warning_var.set(False)
                self._last_risky_set = risky_set

            # Show the warning frame inside the warnings row
            if not self._content_warning_frame.winfo_ismapped():
                self._content_warning_frame.pack(side="left", fill="both", expand=True, padx=(0, 6))
        else:
            # Hide the warning frame
            self._content_warning_frame.pack_forget()
            self._last_risky_set = set()
            self._content_warning_var.set(False)

        self._update_warnings_row()

    def _update_overwrite_warning(self) -> None:
        """Show/hide the overwrite warning banner based on existing expression selections."""
        if not self._overwrite_warning_frame:
            return

        # Collect all selected existing expressions
        replacements = []
        for pose_letter, expr_vars in self._existing_expr_vars.items():
            if self._existing_outfit_vars.get(pose_letter, tk.IntVar()).get() != 1:
                continue
            existing = self._existing_expressions_data.get(pose_letter, [])
            for expr_num, var in expr_vars.items():
                if var.get() == 1 and expr_num in existing:
                    replacements.append((pose_letter, expr_num))

        overwrite_set = set(replacements)

        if replacements:
            # Build description listing what will be replaced
            lines = ["The following existing expressions will be overwritten:\n"]
            for pose, expr in sorted(replacements):
                lines.append(f"  \u2022 Pose {pose.upper()} - Expression {expr}")
            self._overwrite_warning_label.configure(text="\n".join(lines))

            # If overwrite set changed, reset acknowledgment
            if overwrite_set != self._last_overwrite_set:
                self._overwrite_warning_var.set(False)
                self._last_overwrite_set = overwrite_set

            # Show the warning frame inside the warnings row
            if not self._overwrite_warning_frame.winfo_ismapped():
                self._overwrite_warning_frame.pack(side="left", fill="both", expand=True, padx=(6, 0))
        else:
            # Hide the warning frame
            self._overwrite_warning_frame.pack_forget()
            self._last_overwrite_set = set()
            self._overwrite_warning_var.set(False)

        self._update_warnings_row()

    def _update_add_buttons(self) -> None:
        """Update add button states based on current counts."""
        if self._add_outfit_btn:
            if self._get_total_outfit_count() >= self.MAX_OUTFITS:
                self._add_outfit_btn.configure(state="disabled")
            else:
                self._add_outfit_btn.configure(state="normal")

        if self._add_expression_btn:
            if self._get_total_expression_count() >= self.MAX_EXPRESSIONS:
                self._add_expression_btn.configure(state="disabled")
            else:
                self._add_expression_btn.configure(state="normal")

    def _add_custom_outfit(self) -> None:
        """Add a new custom outfit entry."""
        if self._get_total_outfit_count() >= self.MAX_OUTFITS:
            messagebox.showwarning("Limit Reached", f"Maximum {self.MAX_OUTFITS} outfits allowed.")
            return

        row = tk.Frame(self._custom_outfits_frame, bg=BG_COLOR)
        row.pack(fill="x", pady=2)

        # Name entry
        tk.Label(row, text="Name:", bg=BG_COLOR, fg=TEXT_SECONDARY, font=SMALL_FONT).pack(side="left")
        name_entry = tk.Entry(row, width=12, bg="#1E1E1E", fg=TEXT_COLOR, font=SMALL_FONT)
        name_entry.pack(side="left", padx=(4, 8))

        # Description entry
        tk.Label(row, text="Description:", bg=BG_COLOR, fg=TEXT_SECONDARY, font=SMALL_FONT).pack(side="left")
        desc_entry = tk.Entry(row, width=25, bg="#1E1E1E", fg=TEXT_COLOR, font=SMALL_FONT)
        desc_entry.pack(side="left", padx=(4, 8))

        # Remove button
        entry_data = {"frame": row, "name_entry": name_entry, "desc_entry": desc_entry}
        remove_btn = create_secondary_button(
            row, "-", lambda d=entry_data: self._remove_custom_outfit(d), width=3
        )
        remove_btn.pack(side="left")

        self._custom_outfits.append(entry_data)
        self._update_add_buttons()

    def _remove_custom_outfit(self, entry_data: Dict) -> None:
        """Remove a custom outfit entry."""
        if entry_data in self._custom_outfits:
            self._custom_outfits.remove(entry_data)
            entry_data["frame"].destroy()
            self._update_add_buttons()

    def _add_custom_outfit_with_data(self, name: str, desc: str) -> bool:
        """Add a custom outfit entry pre-filled with name and description.

        Returns True if added, False if at limit.
        """
        if self._get_total_outfit_count() >= self.MAX_OUTFITS:
            return False

        row = tk.Frame(self._custom_outfits_frame, bg=BG_COLOR)
        row.pack(fill="x", pady=2)

        tk.Label(row, text="Name:", bg=BG_COLOR, fg=TEXT_SECONDARY, font=SMALL_FONT).pack(side="left")
        name_entry = tk.Entry(row, width=12, bg="#1E1E1E", fg=TEXT_COLOR, font=SMALL_FONT)
        name_entry.pack(side="left", padx=(4, 8))
        name_entry.insert(0, name)

        tk.Label(row, text="Description:", bg=BG_COLOR, fg=TEXT_SECONDARY, font=SMALL_FONT).pack(side="left")
        desc_entry = tk.Entry(row, width=25, bg="#1E1E1E", fg=TEXT_COLOR, font=SMALL_FONT)
        desc_entry.pack(side="left", padx=(4, 8))
        desc_entry.insert(0, desc)

        entry_data = {"frame": row, "name_entry": name_entry, "desc_entry": desc_entry}
        remove_btn = create_secondary_button(
            row, "-", lambda d=entry_data: self._remove_custom_outfit(d), width=3
        )
        remove_btn.pack(side="left")

        self._custom_outfits.append(entry_data)
        self._update_add_buttons()
        return True

    def _open_saved_outfits_dialog(self) -> None:
        """Open a popup dialog to manage and load saved custom outfits."""
        saved = load_saved_outfits()

        dialog = tk.Toplevel(self.wizard.root)
        dialog.title("Saved Outfits")
        dialog.configure(bg=BG_COLOR)
        dialog.geometry("550x600")
        dialog.resizable(False, True)
        dialog.transient(self.wizard.root)
        dialog.grab_set()

        # Title
        tk.Label(
            dialog, text="Saved Outfits", bg=BG_COLOR, fg=TEXT_COLOR, font=SECTION_FONT,
        ).pack(pady=(12, 8))

        # Scrollable list area
        list_frame = tk.Frame(dialog, bg=BG_COLOR)
        list_frame.pack(fill="both", expand=True, padx=12)

        list_canvas = tk.Canvas(list_frame, bg=BG_COLOR, highlightthickness=0)
        list_scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=list_canvas.yview)
        list_canvas.configure(yscrollcommand=list_scrollbar.set)

        list_scrollbar.pack(side="right", fill="y")
        list_canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(list_canvas, bg=BG_COLOR)
        canvas_window_id = list_canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: list_canvas.configure(scrollregion=list_canvas.bbox("all")))
        # Stretch inner frame to fill canvas width so cards span full width
        list_canvas.bind("<Configure>", lambda e: list_canvas.itemconfigure(canvas_window_id, width=e.width))

        # Scroll wheel isolation — only scroll this canvas, not the parent
        def on_popup_scroll(event):
            list_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

        list_canvas.bind("<MouseWheel>", on_popup_scroll)
        inner.bind("<MouseWheel>", on_popup_scroll)

        # Track checkboxes and their indices
        check_vars = []

        def rebuild_list():
            """Rebuild the saved outfits list from current data."""
            nonlocal saved, check_vars
            saved = load_saved_outfits()
            check_vars.clear()
            for w in inner.winfo_children():
                w.destroy()

            if not saved:
                tk.Label(
                    inner, text="No saved outfits yet.\nUse the form below to save one.",
                    bg=BG_COLOR, fg=TEXT_SECONDARY, font=BODY_FONT, justify="center",
                ).pack(pady=20)
                return

            for i, outfit in enumerate(saved):
                item = tk.Frame(inner, bg=CARD_BG, padx=8, pady=6)
                item.pack(fill="x", pady=(0, 4))
                item.bind("<MouseWheel>", on_popup_scroll)

                var = tk.IntVar(value=0)
                check_vars.append((var, i))

                top_row = tk.Frame(item, bg=CARD_BG)
                top_row.pack(fill="x")
                top_row.bind("<MouseWheel>", on_popup_scroll)

                cb = ttk.Checkbutton(top_row, variable=var, style="Dark.TCheckbutton")
                cb.pack(side="left")

                tk.Label(
                    top_row, text=outfit["name"], bg=CARD_BG, fg=TEXT_COLOR,
                    font=SMALL_FONT_BOLD, anchor="w",
                ).pack(side="left", padx=(4, 0))

                # Delete button
                def make_delete(idx=i):
                    def do_delete():
                        delete_saved_outfit(idx)
                        rebuild_list()
                    return do_delete

                create_secondary_button(
                    top_row, "X", make_delete(), width=2
                ).pack(side="right")

                # Description preview (truncated)
                desc_text = outfit.get("description", "")
                if len(desc_text) > 100:
                    desc_text = desc_text[:97] + "..."
                desc_label = tk.Label(
                    item, text=desc_text, bg=CARD_BG, fg=TEXT_SECONDARY,
                    font=SMALL_FONT, anchor="w", wraplength=450, justify="left",
                )
                desc_label.pack(fill="x", padx=(28, 0))
                desc_label.bind("<MouseWheel>", on_popup_scroll)

        rebuild_list()

        # Separator
        tk.Frame(dialog, bg=BORDER_COLOR, height=1).pack(fill="x", padx=12, pady=(8, 0))

        # Save New section
        save_frame = tk.Frame(dialog, bg=BG_COLOR)
        save_frame.pack(fill="x", padx=12, pady=(8, 4))

        tk.Label(save_frame, text="Save New Outfit:", bg=BG_COLOR, fg=TEXT_COLOR, font=SMALL_FONT_BOLD).pack(anchor="w")

        name_row = tk.Frame(save_frame, bg=BG_COLOR)
        name_row.pack(fill="x", pady=(4, 2))
        tk.Label(name_row, text="Name:", bg=BG_COLOR, fg=TEXT_SECONDARY, font=SMALL_FONT).pack(side="left")
        new_name = tk.Entry(name_row, width=20, bg="#1E1E1E", fg=TEXT_COLOR, font=SMALL_FONT, insertbackground=TEXT_COLOR)
        new_name.pack(side="left", padx=(4, 0), fill="x", expand=True)

        desc_row = tk.Frame(save_frame, bg=BG_COLOR)
        desc_row.pack(fill="x", pady=(2, 4))
        tk.Label(desc_row, text="Desc:", bg=BG_COLOR, fg=TEXT_SECONDARY, font=SMALL_FONT).pack(side="left")
        new_desc = tk.Entry(desc_row, width=40, bg="#1E1E1E", fg=TEXT_COLOR, font=SMALL_FONT, insertbackground=TEXT_COLOR)
        new_desc.pack(side="left", padx=(4, 0), fill="x", expand=True)

        def do_save():
            n = new_name.get().strip()
            d = new_desc.get().strip()
            if not n:
                messagebox.showwarning("Missing Name", "Enter a name for the outfit.", parent=dialog)
                return
            if not d:
                messagebox.showwarning("Missing Description", "Enter a description for the outfit.", parent=dialog)
                return
            save_outfit(n, d)
            new_name.delete(0, "end")
            new_desc.delete(0, "end")
            rebuild_list()

        create_secondary_button(save_frame, "Save to List", do_save, width=12).pack(anchor="e")

        # Separator
        tk.Frame(dialog, bg=BORDER_COLOR, height=1).pack(fill="x", padx=12, pady=(4, 0))

        # Action buttons
        btn_frame = tk.Frame(dialog, bg=BG_COLOR)
        btn_frame.pack(fill="x", padx=12, pady=(8, 12))

        def do_add_selected():
            selected = [(var, idx) for var, idx in check_vars if var.get() == 1]
            if not selected:
                messagebox.showinfo("No Selection", "Check at least one outfit to add.", parent=dialog)
                return

            current_saved = load_saved_outfits()
            added = 0
            skipped = 0
            for var, idx in selected:
                if idx < len(current_saved):
                    outfit = current_saved[idx]
                    if self._add_custom_outfit_with_data(outfit["name"], outfit["description"]):
                        added += 1
                    else:
                        skipped += 1

            dialog.destroy()
            if skipped > 0:
                messagebox.showinfo(
                    "Limit Reached",
                    f"Added {added} outfit(s). {skipped} skipped (max {self.MAX_OUTFITS} outfits)."
                )

        create_primary_button(btn_frame, "Add Selected", do_add_selected, width=14).pack(side="right", padx=(8, 0))
        create_secondary_button(btn_frame, "Cancel", dialog.destroy, width=10).pack(side="right")

    def _add_custom_expression(self) -> None:
        """Add a new custom expression entry with auto-incremented key."""
        if self._get_total_expression_count() >= self.MAX_EXPRESSIONS:
            messagebox.showwarning("Limit Reached", f"Maximum {self.MAX_EXPRESSIONS} expressions allowed.")
            return

        # Calculate next available key (auto-increment from highest used key)
        used_keys = set()
        for key, _ in EXPRESSIONS_SEQUENCE:
            try:
                used_keys.add(int(key))
            except ValueError:
                pass
        for entry_data in self._custom_expressions:
            k = entry_data["key_entry"].get().strip()
            if k:
                try:
                    used_keys.add(int(k))
                except ValueError:
                    pass

        # Find next number starting from 13 (after standard expressions)
        next_key = 13
        while next_key in used_keys:
            next_key += 1

        row = tk.Frame(self._custom_expressions_frame, bg=BG_COLOR)
        row.pack(fill="x", pady=2)

        # Key label (read-only, auto-assigned)
        tk.Label(row, text=f"Key: {next_key}", bg=BG_COLOR, fg=ACCENT_COLOR, font=SMALL_FONT).pack(side="left")

        # Hidden entry to store the key value
        key_entry = tk.Entry(row, width=4)
        key_entry.insert(0, str(next_key))
        # Don't pack - just store the value

        # Description entry
        tk.Label(row, text="Description:", bg=BG_COLOR, fg=TEXT_SECONDARY, font=SMALL_FONT).pack(side="left", padx=(8, 0))
        desc_entry = tk.Entry(row, width=30, bg="#1E1E1E", fg=TEXT_COLOR, font=SMALL_FONT)
        desc_entry.pack(side="left", padx=(4, 8))
        desc_entry.focus_set()

        # Remove button
        entry_data = {"frame": row, "key_entry": key_entry, "desc_entry": desc_entry}
        remove_btn = create_secondary_button(
            row, "-", lambda d=entry_data: self._remove_custom_expression(d), width=3
        )
        remove_btn.pack(side="left")

        self._custom_expressions.append(entry_data)
        self._update_add_buttons()

    def _remove_custom_expression(self, entry_data: Dict) -> None:
        """Remove a custom expression entry."""
        if entry_data in self._custom_expressions:
            self._custom_expressions.remove(entry_data)
            entry_data["frame"].destroy()
            self._update_add_buttons()

    def _existing_match_new_outfits(self) -> None:
        """Auto-select the same expressions for existing outfits as chosen for new outfits.

        Only selects missing expressions — existing (on-disk) expressions are never
        auto-selected since replacing them is a destructive action.
        """
        # Get currently selected new-outfit expressions
        selected_new = set()
        for key, var in self._expr_vars.items():
            if var.get() == 1:
                selected_new.add(key)

        for pose_letter, expr_vars in self._existing_expr_vars.items():
            existing = self._existing_expressions_data.get(pose_letter, [])
            # Enable the pose
            if pose_letter in self._existing_outfit_vars:
                self._existing_outfit_vars[pose_letter].set(1)
            # Select matching expressions (skip existing on-disk ones)
            for expr_num, expr_var in expr_vars.items():
                if expr_num in existing:
                    continue  # Don't auto-select existing expressions
                expr_var.set(1 if expr_num in selected_new else 0)
            # Update chip appearances (skip existing)
            if pose_letter in self._existing_expr_chips:
                for expr_num, chip in self._existing_expr_chips[pose_letter].items():
                    if expr_num in existing:
                        continue
                    chip.selected = expr_num in selected_new
        self._update_overwrite_warning()

    def _existing_select_all_missing(self) -> None:
        """Select all missing expressions for all existing outfits.

        Only selects missing expressions — existing (on-disk) expressions are never
        auto-selected since replacing them is a destructive action.
        """
        for pose_letter, expr_vars in self._existing_expr_vars.items():
            existing = self._existing_expressions_data.get(pose_letter, [])
            if pose_letter in self._existing_outfit_vars:
                self._existing_outfit_vars[pose_letter].set(1)
            for expr_num, expr_var in expr_vars.items():
                if expr_num in existing:
                    continue  # Don't auto-select existing expressions
                expr_var.set(1)
            if pose_letter in self._existing_expr_chips:
                for expr_num, chip in self._existing_expr_chips[pose_letter].items():
                    if expr_num in existing:
                        continue
                    chip.selected = True
        self._update_overwrite_warning()

    def _build_existing_outfits_ui(self) -> None:
        """Build UI for adding expressions to existing outfits with chip-based display."""
        # Clear previous content
        for widget in self._existing_poses_content.winfo_children():
            widget.destroy()
        self._existing_outfit_vars.clear()
        self._existing_expr_vars.clear()
        self._existing_expr_chips.clear()
        self._existing_expressions_data.clear()

        if not self.state.existing_character_folder:
            return

        char_folder = self.state.existing_character_folder
        sprite_creator_poses = self.state.sprite_creator_poses or []

        # Expression short names for display
        expr_short_names = {
            "0": "Neutral", "1": "Talking", "2": "Happy", "3": "Sad",
            "4": "Angry", "5": "Surprised", "6": "Embarrassed", "7": "Confused",
            "8": "Laughing", "9": "Scared", "10": "Crying", "11": "Skeptical",
            "12": "Pensive", "13": "Confident", "14": "Playful",
            "15": "Sleepy", "16": "Aroused",
        }

        # Get currently selected new-outfit expressions for auto-default
        selected_new = set()
        for key, var in self._expr_vars.items():
            if var.get() == 1:
                selected_new.add(key)

        for pose_letter in sorted(sprite_creator_poses):
            pose_dir = char_folder / pose_letter
            face_dir = pose_dir / "faces" / "face"

            if not face_dir.is_dir():
                continue

            # Scan existing expressions
            existing_exprs = []
            for f in face_dir.iterdir():
                if f.suffix.lower() in [".png", ".webp"]:
                    expr_num = f.stem
                    if expr_num.isdigit():
                        existing_exprs.append(expr_num)

            self._existing_expressions_data[pose_letter] = existing_exprs

            # Get outfit name
            outfit_name = ""
            outfits_dir = pose_dir / "outfits"
            if outfits_dir.is_dir():
                for f in outfits_dir.iterdir():
                    if f.suffix.lower() in [".png", ".webp"]:
                        outfit_name = f.stem
                        break

            label_text = f"Pose {pose_letter.upper()} - {outfit_name}" if outfit_name else f"Pose {pose_letter.upper()}"

            # Pose card
            pose_frame = tk.Frame(self._existing_poses_content, bg=CARD_BG, padx=10, pady=8,
                                  highlightbackground=BORDER_COLOR, highlightthickness=1)
            pose_frame.pack(fill="x", pady=4)

            # Header with toggle
            header_frame = tk.Frame(pose_frame, bg=CARD_BG)
            header_frame.pack(fill="x")

            pose_var = tk.IntVar(value=0)
            self._existing_outfit_vars[pose_letter] = pose_var

            pose_toggle = tk.Button(
                header_frame,
                text=label_text,
                command=lambda pl=pose_letter: self._toggle_existing_pose(pl),
                bg="#555555",
                fg=TEXT_COLOR,
                activebackground="#666666",
                activeforeground=TEXT_COLOR,
                font=SMALL_FONT_BOLD,
                relief="flat",
                cursor="hand2",
                bd=0,
                padx=10,
                pady=2,
            )
            pose_toggle.pack(side="left")
            pose_frame._toggle_btn = pose_toggle

            # Count of what will be added
            missing_count = sum(1 for k, _ in EXPRESSIONS_SEQUENCE if k not in existing_exprs and k != "0")
            tk.Label(
                header_frame,
                text=f"{len(existing_exprs) - (1 if '0' in existing_exprs else 0)} replaceable, {missing_count} missing",
                bg=CARD_BG,
                fg=TEXT_SECONDARY,
                font=SMALL_FONT,
            ).pack(side="right")

            # Expression chips grid
            chips_frame = tk.Frame(pose_frame, bg=CARD_BG)
            chips_frame.pack(fill="x", pady=(6, 0))

            self._existing_expr_vars[pose_letter] = {}
            self._existing_expr_chips[pose_letter] = {}

            col = 0
            row_num = 0
            for expr_num, expr_desc in EXPRESSIONS_SEQUENCE:
                short = expr_short_names.get(expr_num, expr_num)
                chip_text = f"{expr_num} - {short}"

                if expr_num == "0" and expr_num in existing_exprs:
                    # Expression 0 (Neutral) is copied from the outfit image — never replaceable
                    chip = FilledChip(chips_frame, chip_text)
                    chip.grid(row=row_num, column=col, padx=2, pady=2, sticky="w")
                elif expr_num in existing_exprs:
                    # Already exists - warning-style chip (orange/red)
                    expr_var = tk.IntVar(value=0)
                    self._existing_expr_vars[pose_letter][expr_num] = expr_var

                    def make_existing_toggle(v=expr_var):
                        def on_toggle(selected):
                            v.set(1 if selected else 0)
                            self._update_overwrite_warning()
                        return on_toggle

                    chip = create_toggle_chip(
                        chips_frame, chip_text, selected=False,
                        on_toggle=make_existing_toggle(), style="warning",
                        enabled=False,
                    )
                    chip.grid(row=row_num, column=col, padx=2, pady=2, sticky="w")
                    self._existing_expr_chips[pose_letter][expr_num] = chip
                else:
                    # Missing - toggleable chip, default to unselected
                    expr_var = tk.IntVar(value=0)
                    self._existing_expr_vars[pose_letter][expr_num] = expr_var

                    def make_toggle(v=expr_var):
                        def on_toggle(selected):
                            v.set(1 if selected else 0)
                        return on_toggle

                    chip = create_toggle_chip(
                        chips_frame,
                        chip_text,
                        selected=False,
                        on_toggle=make_toggle(),
                        enabled=False,
                    )
                    chip.grid(row=row_num, column=col, padx=2, pady=2, sticky="w")
                    self._existing_expr_chips[pose_letter][expr_num] = chip

                col += 1
                if col >= 4:
                    col = 0
                    row_num += 1

            # Also include custom expressions from the current session
            current_custom_keys = set()
            for entry_data in self._custom_expressions:
                ckey = entry_data["key_entry"].get().strip()
                cdesc = entry_data["desc_entry"].get().strip()
                if ckey and cdesc:
                    current_custom_keys.add(ckey)
                    if ckey not in existing_exprs:
                        chip_text = f"{ckey} - {cdesc[:12]}"
                        expr_var = tk.IntVar(value=0)
                        self._existing_expr_vars[pose_letter][ckey] = expr_var

                        def make_custom_toggle(v=expr_var):
                            def on_toggle(selected):
                                v.set(1 if selected else 0)
                            return on_toggle

                        chip = create_toggle_chip(
                            chips_frame,
                            chip_text,
                            selected=False,
                            on_toggle=make_custom_toggle(),
                            enabled=False,
                        )
                        chip.grid(row=row_num, column=col, padx=2, pady=2, sticky="w")
                        self._existing_expr_chips[pose_letter][ckey] = chip

                        col += 1
                        if col >= 4:
                            col = 0
                            row_num += 1
                    else:
                        # Custom expression already exists on disk - warning-style chip
                        chip_text = f"{ckey} - {cdesc[:12]}"
                        expr_var = tk.IntVar(value=0)
                        self._existing_expr_vars[pose_letter][ckey] = expr_var

                        def make_existing_custom_toggle(v=expr_var):
                            def on_toggle(selected):
                                v.set(1 if selected else 0)
                                self._update_overwrite_warning()
                            return on_toggle

                        chip = create_toggle_chip(
                            chips_frame, chip_text, selected=False,
                            on_toggle=make_existing_custom_toggle(), style="warning",
                            enabled=False,
                        )
                        chip.grid(row=row_num, column=col, padx=2, pady=2, sticky="w")
                        self._existing_expr_chips[pose_letter][ckey] = chip
                        col += 1
                        if col >= 4:
                            col = 0
                            row_num += 1

            # Show previous-session custom expressions found on disk but not in standard list
            standard_keys = set(expr_num for expr_num, _ in EXPRESSIONS_SEQUENCE)
            extra_on_disk = [e for e in existing_exprs
                            if e not in standard_keys and e not in current_custom_keys and e != "0"]
            for expr_num in sorted(extra_on_disk, key=lambda x: int(x) if x.isdigit() else 999):
                chip_text = f"{expr_num} - Custom"
                expr_var = tk.IntVar(value=0)
                self._existing_expr_vars[pose_letter][expr_num] = expr_var

                def make_extra_toggle(v=expr_var):
                    def on_toggle(selected):
                        v.set(1 if selected else 0)
                        self._update_overwrite_warning()
                    return on_toggle

                chip = create_toggle_chip(
                    chips_frame, chip_text, selected=False,
                    on_toggle=make_extra_toggle(), style="warning",
                    enabled=False,
                )
                chip.grid(row=row_num, column=col, padx=2, pady=2, sticky="w")
                self._existing_expr_chips[pose_letter][expr_num] = chip
                col += 1
                if col >= 4:
                    col = 0
                    row_num += 1

            # Note if all standard expressions already exist
            if len(existing_exprs) >= len(EXPRESSIONS_SEQUENCE):
                tk.Label(
                    chips_frame,
                    text="All standard expressions exist \u2014 select any to replace",
                    bg=CARD_BG,
                    fg=WARNING_TEXT,
                    font=SMALL_FONT,
                ).grid(row=row_num + 1, column=0, columnspan=4, sticky="w", pady=4)

            # Update card highlight and chip enabled state based on toggle
            def update_pose_highlight(pl=pose_letter, pf=pose_frame, pt=pose_toggle):
                def callback(*args):
                    selected = self._existing_outfit_vars[pl].get() == 1
                    pf.configure(
                        highlightbackground=ACCENT_COLOR if selected else BORDER_COLOR,
                        highlightthickness=2 if selected else 1,
                    )
                    pt.configure(bg=ACCENT_COLOR if selected else "#555555")
                    # Enable/disable expression chips when outfit is toggled
                    if pl in self._existing_expr_chips:
                        for chip in self._existing_expr_chips[pl].values():
                            chip.set_enabled(selected)
                return callback

            pose_var.trace_add("write", update_pose_highlight())

    def _toggle_existing_pose(self, pose_letter: str) -> None:
        """Toggle an existing pose for expression extension."""
        var = self._existing_outfit_vars[pose_letter]
        var.set(0 if var.get() else 1)
        self._update_overwrite_warning()

    def on_enter(self) -> None:
        """Prepare options step based on archetype."""
        # Update tip for mode
        if self.state.is_adding_to_existing:
            self._update_tip(
                "Pick new outfits to generate. You can also select existing outfits "
                "below to generate new expressions for them."
            )
        else:
            self._update_tip(self.STEP_TIP)

        # Hide "Include Original Image as Outfit" in add-to-existing mode (irrelevant)
        if self.state.is_adding_to_existing:
            self._base_outfit_frame.pack_forget()
            self._use_base_as_outfit_var.set(0)
        else:
            self._base_outfit_frame.pack(fill="x", pady=(0, 12))

        # Update add button states
        self._update_add_buttons()

        # Update expression count
        self._update_expr_count()

        # Update content warning based on current selections
        self._update_content_warning()

        # Show/hide existing outfits section for add-to-existing mode
        if self.state.is_adding_to_existing and self.state.sprite_creator_poses:
            self._build_existing_outfits_ui()
            self._existing_outfits_section.pack(fill="x", pady=(12, 0))
            # Bind mousewheel to existing outfits canvas and its children
            self._bind_mousewheel_to_canvas(self._existing_poses_content, self._existing_poses_canvas)
            self._bind_mousewheel_to_canvas(self._existing_poses_canvas, self._existing_poses_canvas)
        else:
            self._existing_outfits_section.pack_forget()

        # Update overwrite warning (fresh build = no selections = hidden)
        self._update_overwrite_warning()

        # Bind mousewheel scrolling to all scrollable areas
        if self._outfit_canvas:
            self._bind_mousewheel_to_canvas(self._outfit_scroll_frame, self._outfit_canvas)
            self._bind_mousewheel_to_canvas(self._outfit_canvas, self._outfit_canvas)
        if self._expr_canvas and self._expr_inner_frame:
            self._bind_mousewheel_to_canvas(self._expr_inner_frame, self._expr_canvas)
            self._bind_mousewheel_to_canvas(self._expr_canvas, self._expr_canvas)

    def validate(self) -> bool:
        # Check content filter acknowledgment
        risky = self._get_risky_settings()
        if risky and not self._content_warning_var.get():
            messagebox.showwarning(
                "Acknowledgment Required",
                "Please check the content filter acknowledgment before continuing.\n\n"
                "Some of your selections may be blocked by Gemini's safety filters."
            )
            return False

        # Check overwrite warning acknowledgment
        if self._last_overwrite_set and not self._overwrite_warning_var.get():
            messagebox.showwarning(
                "Acknowledgment Required",
                "Please check the expression overwrite acknowledgment before continuing.\n\n"
                "Some existing expressions will be replaced with newly generated ones."
            )
            return False

        # Build selected outfits and config
        selected = []
        config = {}

        for key in ALL_OUTFIT_KEYS:
            if self._outfit_vars[key].get() == 1:
                selected.append(key)
                mode = self._outfit_mode_vars[key].get()

                use_random = mode in ("random", "standard_uniform")
                custom_prompt = None
                use_standard = mode == "standard_uniform"

                if mode == "custom":
                    custom_prompt = self._outfit_entries[key].get().strip()
                    if not custom_prompt:
                        messagebox.showerror(
                            "Missing Custom Prompt",
                            f"Please enter a custom prompt for {key.capitalize()}, "
                            f"or switch to Random mode."
                        )
                        return False

                config[key] = {
                    "use_random": use_random,
                    "custom_prompt": custom_prompt,
                    "use_standard_uniform": use_standard,
                }

        # Add custom outfits
        for entry_data in self._custom_outfits:
            name = entry_data["name_entry"].get().strip()
            desc = entry_data["desc_entry"].get().strip()
            if not name:
                messagebox.showerror("Missing Name", "Please enter a name for all custom outfits.")
                return False
            if not desc:
                messagebox.showerror("Missing Description", f"Please enter a description for custom outfit '{name}'.")
                return False

            # Use sanitized name as key
            key = f"custom_{name.lower().replace(' ', '_')}"
            selected.append(key)
            config[key] = {
                "use_random": False,
                "custom_prompt": desc,
                "use_standard_uniform": False,
            }

        # Build expression sequence
        expr_seq = [EXPRESSIONS_SEQUENCE[0]]  # Always include neutral
        for key, desc in EXPRESSIONS_SEQUENCE[1:]:
            if self._expr_vars.get(key, tk.IntVar(value=0)).get() == 1:
                expr_seq.append((key, desc))

        # Add custom expressions
        for entry_data in self._custom_expressions:
            key = entry_data["key_entry"].get().strip()
            desc = entry_data["desc_entry"].get().strip()
            if not key:
                messagebox.showerror("Missing Key", "Please enter a key (number) for all custom expressions.")
                return False
            if not desc:
                messagebox.showerror("Missing Description", f"Please enter a description for custom expression '{key}'.")
                return False
            expr_seq.append((key, desc))

        # In add-to-existing mode, rename outfits that conflict with existing ones
        if self.state.is_adding_to_existing and self.state.existing_character_folder:
            # Collect existing outfit names from all poses
            existing_outfit_names = set()
            char_folder = self.state.existing_character_folder
            for pose_letter in "abcdefghijklmnopqrstuvwxyz":
                outfits_dir = char_folder / pose_letter / "outfits"
                if outfits_dir.is_dir():
                    for f in outfits_dir.iterdir():
                        if f.suffix.lower() in [".png", ".webp"]:
                            existing_outfit_names.add(f.stem.lower())

            # Rename conflicting outfits (e.g., "formal" -> "formal2")
            renamed_selected = []
            renamed_config = {}
            for outfit_key in selected:
                new_key = outfit_key
                if outfit_key.lower() in existing_outfit_names:
                    # Find next available number
                    counter = 2
                    while f"{outfit_key}{counter}".lower() in existing_outfit_names or \
                          f"{outfit_key}{counter}" in renamed_selected:
                        counter += 1
                    new_key = f"{outfit_key}{counter}"
                    print(f"[INFO] Renamed outfit '{outfit_key}' -> '{new_key}' (name already exists)")
                renamed_selected.append(new_key)
                # Copy config with new key
                if outfit_key in config:
                    renamed_config[new_key] = config[outfit_key]
                elif new_key != outfit_key:
                    # Preserve any existing config for original key
                    renamed_config[new_key] = config.get(outfit_key, {})
            selected = renamed_selected
            config = renamed_config

        self.state.selected_outfits = selected
        self.state.outfit_prompt_config = config
        self.state.expressions_sequence = expr_seq

        # Save base outfit option
        self.state.use_base_as_outfit = bool(self._use_base_as_outfit_var.get())

        log_info(f"OPTIONS: Outfits={selected}, Exprs={[k for k, _ in expr_seq]}, OriginalAsOutfit={self.state.use_base_as_outfit}")

        # Handle add-to-existing mode: collect existing outfits to extend
        # Only process if there are poses created by Sprite Creator
        if self.state.is_adding_to_existing and self.state.sprite_creator_poses:
            existing_to_extend = {}
            for pose_letter, pose_var in self._existing_outfit_vars.items():
                if pose_var.get() == 1:
                    # Collect selected expressions for this pose
                    selected_exprs = []
                    if pose_letter in self._existing_expr_vars:
                        for expr_num, expr_var in self._existing_expr_vars[pose_letter].items():
                            if expr_var.get() == 1:
                                selected_exprs.append(expr_num)
                    if selected_exprs:
                        existing_to_extend[pose_letter] = selected_exprs

            self.state.existing_outfits_to_extend = existing_to_extend
            log_info(f"OPTIONS: existing_outfits_to_extend={existing_to_extend}")

            # For add-to-existing mode, require at least one new outfit OR one existing outfit extension
            has_new_outfits = len(selected) > 0 or self.state.use_base_as_outfit
            has_existing_extensions = len(existing_to_extend) > 0

            if not has_new_outfits and not has_existing_extensions:
                messagebox.showerror(
                    "Nothing Selected",
                    "Please select at least one new outfit to generate, "
                    "or select expressions to add to existing outfits."
                )
                return False

        return True
