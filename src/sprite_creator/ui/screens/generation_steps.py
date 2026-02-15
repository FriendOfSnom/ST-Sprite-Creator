"""
Review wizard step.

- ReviewStep: Step 4 - Review base image and selected options before generation
"""

import tkinter as tk
from tkinter import messagebox
from typing import Optional

from PIL import Image, ImageTk

from ...config import (
    BG_COLOR,
    CARD_BG,
    TEXT_COLOR,
    TEXT_SECONDARY,
    ACCENT_COLOR,
    ERROR_TEXT,
    PAGE_TITLE_FONT,
    BODY_FONT,
    SMALL_FONT,
)
from .base import WizardStep, WizardState


class ReviewStep(WizardStep):
    """
    Step 5: Review Before Generation.

    Review step showing the base image and selected options before
    proceeding to outfit and expression generation. No generation
    happens here - it's purely for reviewing the character and settings.
    """

    STEP_ID = "review"
    STEP_TITLE = "Review"
    STEP_NUMBER = 5
    STEP_HELP = """Review Before Generation

This is your final check before the AI starts generating images.

BASE CHARACTER
Shows the image that will be used as the reference for all outfit and expression generation.

If this doesn't look right, click Back to return to the previous steps.

SUMMARY
Below the image is a compact summary of your character settings, outfits, and expressions.

WHAT HAPPENS NEXT
Clicking "Accept" starts outfit generation:
1. Each selected outfit is generated using your base image
2. Automatic background removal is applied
3. You'll review each outfit and can regenerate or adjust

This process requires API calls to Gemini and may take several minutes depending on how many outfits you selected.

Click Accept when ready to begin generation."""

    def __init__(self, wizard, state: WizardState):
        super().__init__(wizard, state)
        self._preview_label: Optional[tk.Label] = None
        self._preview_frame: Optional[tk.Frame] = None
        self._summary_label: Optional[tk.Label] = None
        self._tk_img: Optional[ImageTk.PhotoImage] = None

    def build_ui(self, parent: tk.Frame) -> None:
        parent.configure(bg=BG_COLOR)

        # Title
        tk.Label(
            parent,
            text="Review Before Generation",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=PAGE_TITLE_FONT,
        ).pack(pady=(0, 8))

        # Centered image frame
        self._preview_frame = tk.Frame(parent, bg=CARD_BG, padx=4, pady=4)
        self._preview_frame.pack(expand=True)

        self._preview_label = tk.Label(
            self._preview_frame,
            text="Loading...",
            bg=CARD_BG,
            fg=TEXT_SECONDARY,
            font=BODY_FONT,
        )
        self._preview_label.pack()

        # Compact summary below image
        self._summary_label = tk.Label(
            parent,
            text="",
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
            wraplength=700,
            justify="center",
        )
        self._summary_label.pack(pady=(12, 0))

    def on_enter(self) -> None:
        """Display base image and summary when step becomes active."""
        # Change Next button to "Accept" for this review step
        if hasattr(self.wizard, '_next_btn') and self.wizard._next_btn:
            self.wizard._next_btn.configure(text="Accept")

        # Display the base image
        self._display_base_image()

        # Display compact summary
        self._display_summary()

        # Set base_pose_path to the cropped image for downstream steps
        if self.state.cropped_image_path and self.state.cropped_image_path.exists():
            self.state.base_pose_path = self.state.cropped_image_path

    def on_exit(self) -> None:
        """Restore Next button text when leaving step."""
        if hasattr(self.wizard, '_next_btn') and self.wizard._next_btn:
            self.wizard._next_btn.configure(text="Next", state="normal")

    def _display_base_image(self) -> None:
        """Display the base character image, large and centered."""
        image_path = None
        if self.state.cropped_image_path and self.state.cropped_image_path.exists():
            image_path = self.state.cropped_image_path
        elif self.state.image_path and self.state.image_path.exists():
            image_path = self.state.image_path

        if image_path is None:
            self._preview_label.configure(
                text="No image available.\nPlease go back to Step 2.",
                fg=ERROR_TEXT,
            )
            return

        try:
            img = Image.open(image_path).convert("RGBA")

            # Larger display: 65% screen height, 40% width
            parent = self._preview_label.winfo_toplevel()
            max_h = int(parent.winfo_screenheight() * 0.65)
            max_w = int(parent.winfo_screenwidth() * 0.40)

            img.thumbnail((max_w, max_h), Image.LANCZOS)

            self._tk_img = ImageTk.PhotoImage(img)
            self._preview_label.configure(
                image=self._tk_img,
                text="",
                width=img.width,
                height=img.height,
            )
        except Exception as e:
            self._preview_label.configure(
                text=f"Error loading image:\n{e}",
                fg=ERROR_TEXT,
            )

    def _display_summary(self) -> None:
        """Display a compact one-line summary below the image."""
        parts = []

        # Name
        if self.state.display_name:
            parts.append(self.state.display_name)

        # Voice
        if self.state.voice:
            parts.append(self.state.voice.capitalize())

        # Archetype
        if self.state.archetype_label:
            parts.append(self.state.archetype_label.title())

        # Outfits count
        outfit_count = len(self.state.selected_outfits) if self.state.selected_outfits else 0
        if self.state.use_base_as_outfit:
            outfit_count += 1
        parts.append(f"{outfit_count} Outfit{'s' if outfit_count != 1 else ''}")

        # Expressions count
        expr_count = len(self.state.expressions_sequence) if self.state.expressions_sequence else 0
        parts.append(f"{expr_count} Expression{'s' if expr_count != 1 else ''}")

        # Existing outfits to extend (add-to-existing mode)
        if self.state.is_adding_to_existing and self.state.existing_outfits_to_extend:
            extend_count = len(self.state.existing_outfits_to_extend)
            parts.append(f"+{extend_count} Existing Outfit{'s' if extend_count != 1 else ''} to Extend")

        summary = "  |  ".join(parts)
        self._summary_label.configure(text=summary, fg=ACCENT_COLOR)

    def validate(self) -> bool:
        """Validate before advancing."""
        if not self.state.cropped_image_path or not self.state.cropped_image_path.exists():
            if not self.state.image_path or not self.state.image_path.exists():
                messagebox.showerror(
                    "No Base Image",
                    "No base image found. Please go back to Step 2."
                )
                return False
        return True

    def should_skip(self) -> bool:
        """Never skip - this step is used for both image and prompt modes."""
        return False

    def is_dirty(self) -> bool:
        """Check if review affects downstream steps."""
        return False  # Review-only, no changes made here

    def get_dirty_steps(self) -> list:
        """Review doesn't invalidate other steps."""
        return []
