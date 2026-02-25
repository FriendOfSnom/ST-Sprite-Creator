"""
Step 5: Mid-Thigh Crop wizard step.

Allows user to select the horizontal crop line for mid-thigh framing.
"""

import tkinter as tk
from pathlib import Path
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
from ..tk_common import create_secondary_button, get_primary_screen
from .base import WizardStep, WizardState


# Line color for crop indicator
LINE_COLOR = "#ff5555"


def compute_display_size(
    screen_w: int,
    screen_h: int,
    img_w: int,
    img_h: int,
    max_w_ratio: float = 0.60,
    max_h_ratio: float = 0.60,
) -> tuple:
    """Compute display dimensions that fit within screen ratios."""
    max_w = int(screen_w * max_w_ratio)
    max_h = int(screen_h * max_h_ratio)
    scale = min(max_w / img_w, max_h / img_h, 1.0)
    return max(1, int(img_w * scale)), max(1, int(img_h * scale))


class CropStep(WizardStep):
    """Step 5: Mid-Thigh Crop - click to set horizontal crop line."""

    STEP_ID = "crop"
    STEP_TITLE = "Crop"
    STEP_HELP = """Mid-Thigh Crop Selection

Click on the image to set where the character should be cropped.

For best results:
- Crop at mid-thigh level (halfway between hip and knee)
- The cropped image will be used for all outfit and expression generation

If you click at or below the bottom of the image, no cropping will be applied.

You can go back if you need to change your source image."""

    def __init__(self, wizard, state: WizardState):
        super().__init__(wizard, state)
        self._canvas: Optional[tk.Canvas] = None
        self._tk_img: Optional[ImageTk.PhotoImage] = None
        self._guide_line_id: Optional[int] = None
        self._original_img: Optional[Image.Image] = None
        self._disp_w: int = 0
        self._disp_h: int = 0
        self._scale_y: float = 1.0
        self._instruction_label: Optional[tk.Label] = None
        self._selected_y: Optional[int] = None  # Track selected crop position

    def build_ui(self, parent: tk.Frame) -> None:
        parent.configure(bg=BG_COLOR)

        # Title
        tk.Label(
            parent,
            text="Select Crop Line",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=PAGE_TITLE_FONT,
        ).pack(pady=(0, 8))

        # Instructions
        self._instruction_label = tk.Label(
            parent,
            text="Click on the image to set the crop line at mid-thigh level.\n"
                 "The red line shows where the image will be cropped.",
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
            justify="center",
        )
        self._instruction_label.pack(pady=(0, 12))

        # Canvas container with background
        canvas_container = tk.Frame(parent, bg=CARD_BG, padx=4, pady=4)
        canvas_container.pack(expand=True)

        # Canvas for image display - will be resized on enter
        self._canvas = tk.Canvas(
            canvas_container,
            width=400,
            height=500,
            bg="black",
            highlightthickness=0,
        )
        self._canvas.pack()

        # Bind mouse events
        self._canvas.bind("<Motion>", self._on_motion)
        self._canvas.bind("<Button-1>", self._on_click)

        # Status label
        self._status_label = tk.Label(
            parent,
            text="",
            bg=BG_COLOR,
            fg=ACCENT_COLOR,
            font=BODY_FONT,
        )
        self._status_label.pack(pady=(12, 0))

    def on_enter(self) -> None:
        """Load and display the image when step becomes active."""
        # Get the image path from state
        if self.state.source_mode == "image" and self.state.image_path:
            image_path = self.state.image_path
        elif self.state.base_pose_path:
            # For prompt mode or after base generation
            image_path = self.state.base_pose_path
        else:
            # No image available yet - this step might be skipped
            return

        try:
            self._original_img = Image.open(image_path).convert("RGBA")
        except Exception as e:
            self._instruction_label.configure(
                text=f"Error loading image: {e}",
                fg=ERROR_TEXT,
            )
            return

        original_w, original_h = self._original_img.size

        # Get screen size from canvas
        self._canvas.update_idletasks()
        parent = self._canvas.winfo_toplevel()
        sw, sh, *_ = get_primary_screen(parent)

        # Compute display size
        self._disp_w, self._disp_h = compute_display_size(
            sw, sh, original_w, original_h,
            max_w_ratio=0.55, max_h_ratio=0.50
        )
        self._scale_y = original_h / max(1, self._disp_h)

        # Resize canvas
        self._canvas.configure(width=self._disp_w, height=self._disp_h)

        # Create display image
        disp_img = self._original_img.resize(
            (self._disp_w, self._disp_h), Image.LANCZOS
        )
        self._tk_img = ImageTk.PhotoImage(disp_img)

        # Draw image
        self._canvas.delete("all")
        self._canvas.create_image(0, 0, anchor="nw", image=self._tk_img)
        self._guide_line_id = None

        # Reset selection
        self._selected_y = None
        self._status_label.configure(text="Move mouse to preview crop line, click to confirm.")

        # Restore previous crop if exists
        if self.state.crop_y is not None:
            disp_y = int(self.state.crop_y / self._scale_y)
            self._draw_line(disp_y)
            self._selected_y = disp_y
            self._status_label.configure(
                text=f"Crop line set at y={self.state.crop_y}. Click to adjust or press Next to continue."
            )

    def _draw_line(self, y: int) -> None:
        """Draw the crop guide line at the given y position."""
        y = max(0, min(int(y), self._disp_h))
        if self._guide_line_id is None:
            self._guide_line_id = self._canvas.create_line(
                0, y, self._disp_w, y,
                fill=LINE_COLOR, width=3
            )
        else:
            self._canvas.coords(self._guide_line_id, 0, y, self._disp_w, y)

    def _on_motion(self, event) -> None:
        """Handle mouse motion - show preview line."""
        if self._original_img is None:
            return
        # Only update if not yet selected, or always show preview
        self._draw_line(event.y)

    def _on_click(self, event) -> None:
        """Handle mouse click - set the crop position."""
        if self._original_img is None:
            return

        disp_y = max(0, min(event.y, self._disp_h))
        self._draw_line(disp_y)
        self._selected_y = disp_y

        # Convert to original image coordinates
        real_y = int(disp_y * self._scale_y)
        original_h = self._original_img.size[1]

        # Store in state
        if real_y >= original_h - 5:
            # Clicked at/below bottom - no crop
            self.state.crop_y = None
            self._status_label.configure(
                text="No crop (clicked at bottom). Click elsewhere to set crop line."
            )
        else:
            self.state.crop_y = real_y
            self._status_label.configure(
                text=f"Crop line set at y={real_y}. Click to adjust or press Next to continue."
            )

    def validate(self) -> bool:
        """Validate that a crop position has been selected (or explicitly skipped)."""
        # Allow proceeding without crop - user may have clicked bottom or we auto-skip
        if self._original_img is None:
            # No image loaded - likely should skip this step
            return True

        # If no selection made at all, require one
        if self._selected_y is None and self.state.crop_y is None:
            # Default to no crop if user just wants to continue
            self.state.crop_y = None

        return True

    def should_skip(self) -> bool:
        """Skip crop step if already handled or no image available."""
        # For image mode, crop is now done in SetupStep (Step 3)
        if self.state.source_mode == "image":
            return True
        # For prompt mode, we skip crop until after base is generated
        if self.state.source_mode == "prompt" and not self.state.base_pose_path:
            return True
        return False

    def is_dirty(self) -> bool:
        """Check if crop has changed."""
        # Crop affects all downstream generation
        return self.state.crop_y is not None

    def get_dirty_steps(self) -> list:
        """Changing crop invalidates base generation and beyond."""
        # Steps 6+ would need regeneration
        return [5, 6, 7, 8, 9, 10]  # All generation steps
