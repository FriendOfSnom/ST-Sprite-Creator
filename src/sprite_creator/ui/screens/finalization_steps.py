"""
Finalization wizard steps (Steps 11-13).

These steps handle final character configuration:
- Step 11: Eye Line & Name Color picker
- Step 12: Scale Selector
- Step 13: Final Summary
"""

import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Optional, Dict

import yaml
from PIL import Image, ImageTk

from ...config import (
    BG_COLOR,
    CARD_BG,
    TEXT_COLOR,
    TEXT_SECONDARY,
    ACCENT_COLOR,
    ERROR_TEXT,
    SUCCESS_COLOR,
    PAGE_TITLE_FONT,
    SECTION_FONT,
    BODY_FONT,
    SMALL_FONT,
    REF_SPRITES_DIR,
    get_backup_dir,
    generate_backup_id,
)
from ..tk_common import (
    create_primary_button,
    create_secondary_button,
    show_error_dialog,
    get_primary_screen,
)
from .base import WizardStep, WizardState
from ...logging_utils import log_info, log_error


# Line color for guides
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


class EyeLineStep(WizardStep):
    """
    Step 8: Eye Line & Name Color picker.

    Two-click interaction:
    1. Click to set eye line (horizontal guide)
    2. Click to pick name color from hair
    """

    STEP_ID = "eye_line"
    STEP_TITLE = "Finalize"
    STEP_NUMBER = 8
    STEP_TIP = (
        "Two clicks needed: first click the character's eyes to set the eye line, "
        "then click the hair to pick the name color."
    )
    STEP_HELP = """Eye Line & Name Color

This step sets two values used by visual novel engines.

STEP 1: EYE LINE
A red horizontal line follows your mouse. Click on the character's eyes to record the position.

What it's for:
The eye line ratio tells the engine where the character's eyes are. This is used to:
- Align multiple characters in conversation
- Position the character's head at a consistent height
- Adjust vertical positioning in dialogue scenes

How to set it:
Move your mouse until the red line is at eye level, then click. The line should pass through the center of both eyes.

After clicking, the step automatically advances to color picking.

STEP 2: NAME COLOR
A crosshair follows your mouse. Click on the character's hair to sample a color.

What it's for:
This color is used when the character's name appears in dialogue boxes. Picking a hair color creates visual consistency.

How to set it:
Click on the most prominent hair color. The sampled color appears in a preview box below.

Tips:
- Avoid clicking on highlights or shadows
- If you click a transparent area, a default brown is used
- You can click again to change the color

AFTER BOTH ARE SET
The status shows both values. Click Next to continue.

If you need to redo:
- You can click again to change the name color
- To redo the eye line, you'll need to go Back and return"""

    def __init__(self, wizard, state: WizardState):
        super().__init__(wizard, state)
        self._canvas: Optional[tk.Canvas] = None
        self._tk_img: Optional[ImageTk.PhotoImage] = None
        self._original_img: Optional[Image.Image] = None
        self._instruction_label: Optional[tk.Label] = None
        self._status_label: Optional[tk.Label] = None
        self._guide_line_id: Optional[int] = None
        self._reticle_h_id: Optional[int] = None
        self._reticle_v_id: Optional[int] = None
        self._disp_w: int = 0
        self._disp_h: int = 0
        self._scale_x: float = 1.0
        self._scale_y: float = 1.0
        self._step: int = 1  # 1=eye line, 2=name color
        self._color_preview: Optional[tk.Label] = None

    def build_ui(self, parent: tk.Frame) -> None:
        parent.configure(bg=BG_COLOR)

        # Title
        tk.Label(
            parent,
            text="Eye Line & Name Color",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=PAGE_TITLE_FONT,
        ).pack(pady=(0, 8))

        self._build_tip_bar(parent)

        # Instructions
        self._instruction_label = tk.Label(
            parent,
            text="Step 1: Click on the character's eyes to set the eye line.",
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=BODY_FONT,
            justify="center",
        )
        self._instruction_label.pack(pady=(0, 12))

        # Canvas container
        canvas_container = tk.Frame(parent, bg=CARD_BG, padx=4, pady=4)
        canvas_container.pack(expand=True)

        self._canvas = tk.Canvas(
            canvas_container,
            width=400,
            height=500,
            bg="black",
            highlightthickness=0,
        )
        self._canvas.pack()

        # Bind events
        self._canvas.bind("<Motion>", self._on_motion)
        self._canvas.bind("<Button-1>", self._on_click)

        # Bottom controls
        bottom_frame = tk.Frame(parent, bg=BG_COLOR)
        bottom_frame.pack(fill="x", pady=(12, 0))

        # Status and color preview
        status_row = tk.Frame(bottom_frame, bg=BG_COLOR)
        status_row.pack()

        self._status_label = tk.Label(
            status_row,
            text="",
            bg=BG_COLOR,
            fg=ACCENT_COLOR,
            font=BODY_FONT,
        )
        self._status_label.pack(side="left")

        self._color_preview = tk.Label(
            status_row,
            text="   ",
            width=4,
            height=1,
            bg=BG_COLOR,
            relief="solid",
            borderwidth=1,
        )
        # Hidden until color is selected

    def on_enter(self) -> None:
        """Load the character image when step becomes active."""
        # Find the best image to use (base pose or final outfit)
        image_path = None
        if self.state.base_pose_path and self.state.base_pose_path.exists():
            image_path = self.state.base_pose_path

        if not image_path:
            self._instruction_label.configure(
                text="No character image available.",
                fg=ERROR_TEXT,
            )
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

        # Get screen dimensions
        parent = self._canvas.winfo_toplevel()
        sw, sh, *_ = get_primary_screen(parent)

        # Compute display size (larger for better picking accuracy)
        self._disp_w, self._disp_h = compute_display_size(
            sw, sh, original_w, original_h,
            max_w_ratio=0.55, max_h_ratio=0.65
        )

        self._scale_x = original_w / max(1, self._disp_w)
        self._scale_y = original_h / max(1, self._disp_h)

        # Resize canvas
        self._canvas.configure(width=self._disp_w, height=self._disp_h)

        # Display image
        disp_img = self._original_img.resize((self._disp_w, self._disp_h), Image.LANCZOS)
        self._tk_img = ImageTk.PhotoImage(disp_img)
        self._canvas.delete("all")
        self._canvas.create_image(0, 0, anchor="nw", image=self._tk_img)

        # Reset state
        self._step = 1
        self._guide_line_id = None
        self._reticle_h_id = None
        self._reticle_v_id = None

        # Restore previous values if exists
        if self.state.eye_line_ratio is not None:
            disp_y = int(self.state.eye_line_ratio * self._disp_h)
            self._draw_eye_line(disp_y)
            self._step = 2
            self._instruction_label.configure(
                text="Step 2: Click on the hair to pick the name color."
            )

        if self.state.name_color:
            self._color_preview.configure(bg=self.state.name_color)
            self._color_preview.pack(side="left", padx=(8, 0))
            self._status_label.configure(
                text=f"Eye line: {self.state.eye_line_ratio:.3f}, Color: {self.state.name_color}"
            )

    def _draw_eye_line(self, y: int) -> None:
        """Draw horizontal eye line guide."""
        y = max(0, min(int(y), self._disp_h))
        if self._guide_line_id is None:
            self._guide_line_id = self._canvas.create_line(
                0, y, self._disp_w, y,
                fill=LINE_COLOR, width=3
            )
        else:
            self._canvas.coords(self._guide_line_id, 0, y, self._disp_w, y)

    def _clear_eye_line(self) -> None:
        """Clear the eye line guide."""
        if self._guide_line_id is not None:
            self._canvas.delete(self._guide_line_id)
            self._guide_line_id = None

    def _draw_reticle(self, x: int, y: int, arm: int = 16) -> None:
        """Draw crosshair reticle for color picking."""
        x = max(0, min(int(x), self._disp_w))
        y = max(0, min(int(y), self._disp_h))
        if self._reticle_h_id is None:
            self._reticle_h_id = self._canvas.create_line(
                x - arm, y, x + arm, y,
                fill=LINE_COLOR, width=2
            )
            self._reticle_v_id = self._canvas.create_line(
                x, y - arm, x, y + arm,
                fill=LINE_COLOR, width=2
            )
        else:
            self._canvas.coords(self._reticle_h_id, x - arm, y, x + arm, y)
            self._canvas.coords(self._reticle_v_id, x, y - arm, x, y + arm)

    def _clear_reticle(self) -> None:
        """Clear the reticle."""
        if self._reticle_h_id is not None:
            self._canvas.delete(self._reticle_h_id)
            self._canvas.delete(self._reticle_v_id)
            self._reticle_h_id = None
            self._reticle_v_id = None

    def _on_motion(self, event) -> None:
        """Handle mouse motion."""
        if self._original_img is None:
            return

        if self._step == 1:
            self._draw_eye_line(event.y)
        elif self._step == 2:
            self._draw_reticle(event.x, event.y)

    def _on_click(self, event) -> None:
        """Handle mouse click."""
        if self._original_img is None:
            return

        if self._step == 1:
            # Record eye line
            real_y = event.y * self._scale_y
            original_h = self._original_img.size[1]
            self.state.eye_line_ratio = real_y / original_h

            self._clear_eye_line()
            self._instruction_label.configure(
                text="Eye line recorded. Step 2: Click on the hair to pick the name color."
            )
            self._step = 2
            self._draw_reticle(event.x, event.y)
            self._status_label.configure(text=f"Eye line: {self.state.eye_line_ratio:.3f}")

        elif self._step == 2:
            # Record name color
            rx = min(max(int(event.x * self._scale_x), 0), self._original_img.size[0] - 1)
            ry = min(max(int(event.y * self._scale_y), 0), self._original_img.size[1] - 1)
            px = self._original_img.getpixel((rx, ry))

            # Check for transparent pixel
            if len(px) == 4 and px[3] < 10:
                color = "#915f40"  # Default brown
            else:
                color = f"#{px[0]:02x}{px[1]:02x}{px[2]:02x}"

            self.state.name_color = color
            self._clear_reticle()

            # Show color preview
            self._color_preview.configure(bg=color)
            self._color_preview.pack(side="left", padx=(8, 0))

            self._status_label.configure(
                text=f"Eye line: {self.state.eye_line_ratio:.3f}, Color: {color}"
            )
            self._instruction_label.configure(
                text="Done! Click 'Next' to continue, or click again to change the color."
            )

    def validate(self) -> bool:
        """Validate that both values are set."""
        if self.state.eye_line_ratio is None:
            messagebox.showerror("Missing Eye Line", "Please click on the character's eyes to set the eye line.")
            return False
        if not self.state.name_color:
            messagebox.showerror("Missing Name Color", "Please click on the hair to pick the name color.")
            return False
        return True


class ScaleStep(WizardStep):
    """
    Step 9: Scale Selector.

    Side-by-side comparison with reference sprites to set character scale.
    """

    STEP_ID = "scale"
    STEP_TITLE = "Scale"
    STEP_NUMBER = 9
    STEP_TIP = (
        "Compare your character side-by-side with a reference sprite "
        "and adjust the scale slider until they match in height."
    )
    STEP_HELP = """Character Scale

This step sets how large your character appears in-game.

HOW IT WORKS
The left canvas shows a reference character at their defined scale.
The right canvas shows one of your generated expressions at the current slider value.

Both are rendered as they would appear in the game engine, anchored at the bottom (standing on the same ground).

REFERENCE DROPDOWN (Left)
Select a reference character to compare against. Choose one that matches your character's age/archetype for best results.

Reference characters have pre-defined scales in their .yml files.

PREVIEW EXPRESSION DROPDOWN (Right)
Select which of your generated expressions to preview. You can switch between different outfits and expression numbers to compare against the reference at the current scale.

SCALE SLIDER
Drag to adjust your character's scale:
- 1.0 = Original image size (no scaling)
- Below 1.0 = Character appears smaller
- Above 1.0 = Character appears larger

The red line on your character shows the eye line position (if set in the previous step). Use this to help match eye levels between characters.

RECOMMENDED APPROACH
1. Pick a reference character of similar type
2. Match the top of your character's head to the reference
3. Or match shoulder heights for more consistent framing
4. Fine-tune with the slider (0.01 increments)

COMMON VALUES
- 0.8 - 1.0: Typical for most characters
- 0.6 - 0.8: Shorter/younger characters
- 1.0 - 1.2: Taller characters

The exact value depends on your game's art style and existing characters.

AUTOMATIC IMAGE SCALING
All generated images are automatically resized using high-quality LANCZOS resampling based on the scale value you choose. This reduces file sizes and ensures consistent display in-game.

ADD-TO-EXISTING MODE
When adding to an existing character:
- Left canvas shows a composite from the existing character
- Right canvas shows your newly generated expression (selectable via dropdown)
- Scale is auto-calculated to match the existing character's image height
- Images are always scaled to ensure consistency

The auto-calculated scale makes the new content appear the same size as the existing character in-game. You can fine-tune if needed.

Click Next when the scale looks right."""

    def __init__(self, wizard, state: WizardState):
        super().__init__(wizard, state)
        self._ref_canvas: Optional[tk.Canvas] = None
        self._user_canvas: Optional[tk.Canvas] = None
        self._scale_var: Optional[tk.DoubleVar] = None
        self._apply_scale_var: Optional[tk.BooleanVar] = None
        self._ref_var: Optional[tk.StringVar] = None
        self._references: Dict[str, dict] = {}
        self._user_img: Optional[Image.Image] = None
        self._img_refs: dict = {"ref": None, "usr": None}
        self._canv_w: int = 360
        self._canv_h: int = 360

        # For add-to-existing mode
        self._apply_scale_frame: Optional[tk.Frame] = None
        self._ref_selector_frame: Optional[tk.Frame] = None
        self._existing_ref_img: Optional[Image.Image] = None
        self._left_label: Optional[tk.Label] = None
        self._new_expr_selector_frame: Optional[tk.Frame] = None
        self._new_expr_images: Dict[str, Image.Image] = {}  # label -> PIL Image
        self._new_expr_var: Optional[tk.StringVar] = None
        self._new_expr_menu: Optional[ttk.Combobox] = None

    def build_ui(self, parent: tk.Frame) -> None:
        parent.configure(bg=BG_COLOR)

        # Title
        tk.Label(
            parent,
            text="Adjust Character Scale",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=PAGE_TITLE_FONT,
        ).pack(pady=(0, 8))

        self._build_tip_bar(parent)

        # Reference selector (hidden in add-to-existing mode)
        self._ref_selector_frame = tk.Frame(parent, bg=BG_COLOR)
        self._ref_selector_frame.pack(pady=(0, 8))

        tk.Label(
            self._ref_selector_frame,
            text="Reference:",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=BODY_FONT,
        ).pack(side="left", padx=(0, 8))

        self._ref_var = tk.StringVar(value="")
        self._ref_menu = ttk.Combobox(
            self._ref_selector_frame, textvariable=self._ref_var,
            state="readonly", width=22
        )
        self._ref_menu.pack(side="left")
        self._ref_menu.bind("<<ComboboxSelected>>", lambda e: self._on_ref_change(self._ref_var.get()))

        # New expression selector (for add-to-existing mode, hidden by default)
        self._new_expr_selector_frame = tk.Frame(parent, bg=BG_COLOR)
        # Don't pack - shown in add-to-existing mode

        tk.Label(
            self._new_expr_selector_frame,
            text="Preview expression:",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=BODY_FONT,
        ).pack(side="left", padx=(0, 8))

        self._new_expr_var = tk.StringVar(value="")
        self._new_expr_menu = ttk.Combobox(
            self._new_expr_selector_frame, textvariable=self._new_expr_var,
            state="readonly", width=27
        )
        self._new_expr_menu.pack(side="left")
        self._new_expr_menu.bind("<<ComboboxSelected>>", lambda e: self._on_new_expr_change(self._new_expr_var.get()))

        # Canvas row
        canvas_frame = tk.Frame(parent, bg=BG_COLOR)
        canvas_frame.pack(fill="both", expand=True, pady=(8, 8))

        # Reference canvas (left)
        left_col = tk.Frame(canvas_frame, bg=BG_COLOR)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 8))

        self._left_label = tk.Label(
            left_col,
            text="Reference",
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        )
        self._left_label.pack()

        self._ref_canvas = tk.Canvas(
            left_col,
            width=self._canv_w,
            height=self._canv_h,
            bg="black",
            highlightthickness=0,
        )
        self._ref_canvas.pack()

        # User canvas (right)
        right_col = tk.Frame(canvas_frame, bg=BG_COLOR)
        right_col.pack(side="left", fill="both", expand=True, padx=(8, 0))

        tk.Label(
            right_col,
            text="Your Character",
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        ).pack()

        self._user_canvas = tk.Canvas(
            right_col,
            width=self._canv_w,
            height=self._canv_h,
            bg="black",
            highlightthickness=0,
        )
        self._user_canvas.pack()

        # Scale slider
        self._scale_var = tk.DoubleVar(value=1.0)
        slider_frame = tk.Frame(parent, bg=BG_COLOR)
        slider_frame.pack(fill="x", pady=(8, 0))

        tk.Label(
            slider_frame,
            text="Scale:",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=BODY_FONT,
        ).pack(side="left", padx=(0, 8))

        self._scale_slider = tk.Scale(
            slider_frame,
            from_=0.1,
            to=2.5,
            resolution=0.01,
            orient=tk.HORIZONTAL,
            variable=self._scale_var,
            length=400,
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            highlightthickness=0,
            command=lambda _: self._update_slider_labels(),
        )
        self._scale_slider.pack(side="left", fill="x", expand=True)
        self._scale_slider.bind("<ButtonRelease-1>", lambda _: self._redraw())

        # Scale value label
        self._scale_label = tk.Label(
            slider_frame,
            text="1.00",
            bg=BG_COLOR,
            fg=ACCENT_COLOR,
            font=BODY_FONT,
            width=6,
        )
        self._scale_label.pack(side="left", padx=(8, 0))

        # Height crop slider (sets image_height in character.yml for in-game cropping)
        self._height_var = tk.IntVar(value=1000)
        height_frame = tk.Frame(parent, bg=BG_COLOR)
        height_frame.pack(fill="x", pady=(4, 0))

        tk.Label(
            height_frame,
            text="Height:",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=BODY_FONT,
        ).pack(side="left", padx=(0, 8))

        self._height_slider = tk.Scale(
            height_frame,
            from_=100,
            to=2000,
            resolution=1,
            orient=tk.HORIZONTAL,
            variable=self._height_var,
            length=400,
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            highlightthickness=0,
            command=lambda _: self._update_slider_labels(),
        )
        self._height_slider.pack(side="left", fill="x", expand=True)
        self._height_slider.bind("<ButtonRelease-1>", lambda _: self._redraw())

        self._height_label = tk.Label(
            height_frame,
            text="1000",
            bg=BG_COLOR,
            fg=ACCENT_COLOR,
            font=BODY_FONT,
            width=6,
        )
        self._height_label.pack(side="left", padx=(8, 0))

        # Apply scale to images checkbox - DEFAULT TO TRUE (scaling on by default)
        # NOTE: Checkbox is hidden - scaling is ALWAYS mandatory for all modes
        # We keep the frame/var for backend compatibility but never show it
        self._apply_scale_var = tk.BooleanVar(value=True)
        self._apply_scale_frame = tk.Frame(parent, bg=CARD_BG, padx=12, pady=8)
        # DO NOT pack - scaling is always mandatory, checkbox should never be visible

        self._apply_scale_checkbox = tk.Checkbutton(
            self._apply_scale_frame,
            text="✓ Scale images to match (recommended - reduces file size)",
            variable=self._apply_scale_var,
            bg=CARD_BG,
            fg=TEXT_COLOR,
            activebackground=CARD_BG,
            activeforeground=TEXT_COLOR,
            selectcolor="#1E1E1E",
            font=BODY_FONT,
        )
        self._apply_scale_checkbox.pack(side="left")

        tk.Label(
            self._apply_scale_frame,
            text="(LANCZOS resampling)",
            bg=CARD_BG,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        ).pack(side="left", padx=(8, 0))

    def on_enter(self) -> None:
        """Load references and user image when step becomes active."""
        # Handle add-to-existing mode differently
        if self.state.is_adding_to_existing:
            self._update_tip(
                "Match your new outfits to the existing character's scale. "
                "The slider auto-calculates from the existing sprite on the left."
            )
            self._setup_add_to_existing_mode()
            return

        self._update_tip(self.STEP_TIP)
        # Normal mode: show both reference selector and expression selector
        self._ref_selector_frame.pack(pady=(0, 8))
        self._new_expr_selector_frame.pack(pady=(0, 8))
        # Scaling is always mandatory - ensure var is True
        self._apply_scale_var.set(True)
        self._left_label.configure(text="Reference")

        self._load_references()

        if not self._references:
            messagebox.showwarning(
                "No References",
                "No reference sprites found. You can still set a scale manually."
            )

        # Update reference dropdown
        names = sorted(self._references.keys())
        self._ref_menu["values"] = names
        if names:
            # Default to "john" if available, otherwise first alphabetically
            default_name = "john" if "john" in names else names[0]
            self._ref_var.set(default_name)

        # Load generated expression images for right side
        # (NOT base_pose_path — that's the cropped input which can differ in
        # resolution from the Gemini-generated images that ST will actually render)
        self._new_expr_images.clear()
        self._user_img = None

        if self.state.expression_paths:
            for outfit_name, expr_dict in self.state.expression_paths.items():
                for expr_key in sorted(expr_dict.keys(), key=lambda x: int(x) if x.isdigit() else 999):
                    path = expr_dict[expr_key]
                    if path and path.exists():
                        try:
                            img = Image.open(path).convert("RGBA")
                            label = f"{outfit_name} - {expr_key}"
                            self._new_expr_images[label] = img
                        except Exception:
                            pass

        # Populate expression dropdown and set default
        if self._new_expr_images:
            labels = list(self._new_expr_images.keys())
            self._new_expr_menu["values"] = labels
            default_label = labels[0]
            self._new_expr_var.set(default_label)
            self._user_img = self._new_expr_images[default_label]
        else:
            self._new_expr_menu["values"] = []

        # Fallback: scan working folder for any generated face
        if not self._user_img:
            working_folder = self.state.character_folder
            if working_folder and working_folder.exists():
                for pose_letter in "abcdefghijklmnopqrstuvwxyz":
                    face_dir = working_folder / pose_letter / "faces" / "face"
                    if face_dir.is_dir():
                        for expr_num in ["0", "1"]:
                            for ext in [".png", ".webp"]:
                                path = face_dir / f"{expr_num}{ext}"
                                if path.exists():
                                    try:
                                        self._user_img = Image.open(path).convert("RGBA")
                                        break
                                    except Exception:
                                        pass
                            if self._user_img:
                                break
                        if self._user_img:
                            break

        # Restore previous scale
        if self.state.scale_factor:
            self._scale_var.set(self.state.scale_factor)

        # Initialize height slider based on user image
        if self._user_img:
            img_h = self._user_img.height
            self._height_slider.configure(to=img_h)
            if self.state.image_height and self.state.image_height <= img_h:
                self._height_var.set(self.state.image_height)
            else:
                self._height_var.set(img_h)
        else:
            self._height_slider.configure(to=2000)
            self._height_var.set(2000)

        # Scaling is always mandatory - always force True
        # (checkbox is hidden but backend var must be True)
        self._apply_scale_var.set(True)

        # Update canvas sizes based on screen (larger for better accuracy)
        parent = self._ref_canvas.winfo_toplevel()
        sw, sh, *_ = get_primary_screen(parent)
        self._canv_w = max(int((sw - 100) // 2.2), 350)
        self._canv_h = max(int(sh * 0.55), 350)

        self._ref_canvas.configure(width=self._canv_w, height=self._canv_h)
        self._user_canvas.configure(width=self._canv_w, height=self._canv_h)

        # Initial draw
        self._redraw()

    def should_skip(self) -> bool:
        """Skip scale step if only extending existing outfits (no new outfits)."""
        if not self.state.is_adding_to_existing:
            return False
        # If there are new outfits, we need the scale step
        has_new_outfits = bool(self.state.generated_outfit_keys)
        if has_new_outfits:
            return False
        # Only extending existing outfits - those expressions are generated from
        # already-scaled images, so they're already at the right size
        return True

    def _setup_add_to_existing_mode(self) -> None:
        """Set up ScaleStep for add-to-existing mode.

        Left side: existing character expression at its YAML scale.
        Right side: newly generated expression with dropdown selector.
        Auto-calc: existing_h / new_h
        """
        # Hide normal reference selector, show new expression selector
        self._ref_selector_frame.pack_forget()
        self._new_expr_selector_frame.pack(pady=(0, 8))

        # Scaling is always mandatory
        self._apply_scale_var.set(True)

        # Update left label
        self._left_label.configure(text="Existing Character")

        # === LEFT SIDE: Load existing character reference as composite ===
        char_folder = self.state.existing_character_folder
        sprite_creator_poses = self.state.sprite_creator_poses or []

        self._existing_ref_img = None

        # Build composite (outfit + face) for a complete character preview.
        # Face-only or outfit-only images are mostly transparent and look blank.
        all_poses = sorted(sprite_creator_poses) if sprite_creator_poses else []
        if not all_poses and char_folder:
            all_poses = sorted(
                p.name for p in char_folder.iterdir()
                if p.is_dir() and len(p.name) == 1 and p.name.isalpha()
            )

        for pose_letter in all_poses:
            pose_dir = char_folder / pose_letter
            outfit_path = None
            face_path = None

            # Find first outfit image (supports flat files and ST subdirectories)
            outfits_dir = pose_dir / "outfits"
            if outfits_dir.is_dir():
                for item in sorted(outfits_dir.iterdir()):
                    if item.is_file() and item.suffix.lower() in [".png", ".webp"]:
                        outfit_path = item
                        break
                    elif item.is_dir():
                        for ext in [".webp", ".png"]:
                            candidate = item / f"{item.name}{ext}"
                            if candidate.exists():
                                outfit_path = candidate
                                break
                    if outfit_path:
                        break

            # Find first face image
            face_dir = pose_dir / "faces" / "face"
            if face_dir.is_dir():
                for expr_num in ["0", "1"]:
                    for ext in [".png", ".webp"]:
                        p = face_dir / f"{expr_num}{ext}"
                        if p.exists():
                            face_path = p
                            break
                    if face_path:
                        break

            # Build composite if we have both
            if outfit_path and face_path:
                try:
                    outfit = Image.open(outfit_path).convert("RGBA")
                    face = Image.open(face_path).convert("RGBA")
                    canvas = Image.new("RGBA", outfit.size, (0, 0, 0, 0))
                    canvas.paste(outfit, (0, 0), outfit)
                    canvas.paste(face, (0, 0), face)
                    self._existing_ref_img = canvas
                    break
                except Exception:
                    pass

            # Fallback: face-only (Sprite Creator chars where face IS full character)
            if not self._existing_ref_img and face_path:
                try:
                    self._existing_ref_img = Image.open(face_path).convert("RGBA")
                    break
                except Exception:
                    pass

            # Fallback: outfit-only
            if not self._existing_ref_img and outfit_path:
                try:
                    self._existing_ref_img = Image.open(outfit_path).convert("RGBA")
                    break
                except Exception:
                    pass

        # Last resort: original.png (or legacy base.png) from character root
        if not self._existing_ref_img:
            base_path = char_folder / "original.png"
            if not base_path.exists():
                base_path = char_folder / "base.png"  # Legacy fallback
            if base_path.exists():
                try:
                    self._existing_ref_img = Image.open(base_path).convert("RGBA")
                except Exception:
                    pass

        # Display at raw pixel size (scale=1.0). The engine applies character.yml
        # scale uniformly to ALL poses later, so we don't pre-bake it here.
        if self._existing_ref_img:
            self._references["existing"] = {"image": self._existing_ref_img, "scale": 1.0}
            self._ref_var.set("existing")

        # === RIGHT SIDE: Load ONLY new outfit expressions (never existing outfit expressions) ===
        self._new_expr_images.clear()
        self._user_img = None

        if self.state.expression_paths:
            for outfit_name, expr_dict in self.state.expression_paths.items():
                # ONLY new outfits - never load existing outfit expressions for scaling
                if outfit_name.startswith("existing_"):
                    continue
                for expr_key in sorted(expr_dict.keys(), key=lambda x: int(x) if x.isdigit() else 999):
                    path = expr_dict[expr_key]
                    if path and path.exists():
                        try:
                            img = Image.open(path).convert("RGBA")
                            label = f"{outfit_name} - {expr_key}"
                            self._new_expr_images[label] = img
                        except Exception:
                            pass

        # Populate dropdown and set default
        if self._new_expr_images:
            labels = list(self._new_expr_images.keys())
            self._new_expr_menu["values"] = labels
            # Default to first expression (usually 0.png)
            default_label = labels[0]
            self._new_expr_var.set(default_label)
            self._user_img = self._new_expr_images[default_label]
        else:
            self._new_expr_menu["values"] = []

        # Fallback: scan working folder for any generated face
        if not self._user_img:
            working_folder = self.state.character_folder
            if working_folder and working_folder.exists():
                for pose_letter in "abcdefghijklmnopqrstuvwxyz":
                    face_dir = working_folder / pose_letter / "faces" / "face"
                    if face_dir.is_dir():
                        for expr_num in ["0", "1"]:
                            for ext in [".png", ".webp"]:
                                path = face_dir / f"{expr_num}{ext}"
                                if path.exists():
                                    try:
                                        self._user_img = Image.open(path).convert("RGBA")
                                        break
                                    except Exception:
                                        pass
                            if self._user_img:
                                break
                        if self._user_img:
                            break

        # === AUTO-CALC: existing_h / new_h ===
        # Match pixel heights only; the engine applies existing_scale uniformly
        # to ALL poses (including ours), so we must NOT pre-bake it here.
        if self._existing_ref_img and self._user_img:
            existing_h = self._existing_ref_img.height
            new_h = self._user_img.height
            initial_scale = existing_h / new_h
            self._scale_var.set(min(max(initial_scale, 0.1), 2.5))
        else:
            self._scale_var.set(1.0)

        # Update canvas sizes
        parent = self._ref_canvas.winfo_toplevel()
        sw, sh, *_ = get_primary_screen(parent)
        self._canv_w = max(int((sw - 100) // 2.2), 350)
        self._canv_h = max(int(sh * 0.55), 350)

        self._ref_canvas.configure(width=self._canv_w, height=self._canv_h)
        self._user_canvas.configure(width=self._canv_w, height=self._canv_h)

        # Initial draw
        self._redraw()

    def _on_new_expr_change(self, label: str) -> None:
        """Handle expression selector change (used in both normal and add-to-existing mode)."""
        self._new_expr_var.set(label)
        if label in self._new_expr_images:
            self._user_img = self._new_expr_images[label]
            self._redraw()

    def _load_references(self) -> None:
        """Load reference sprites from scale_references subdirectory.

        Structure: reference_sprites/scale_references/<character_name>/
                     - <character_name>.png (the sprite image)
                     - character.yml (with scale, eye_line, etc.)
        """
        self._references = {}

        scale_refs_dir = REF_SPRITES_DIR / "scale_references"
        if not scale_refs_dir.is_dir():
            return

        for char_dir in scale_refs_dir.iterdir():
            if not char_dir.is_dir():
                continue

            name = char_dir.name
            # Look for <name>.png in the character folder
            img_path = char_dir / f"{name}.png"
            yml_path = char_dir / "character.yml"

            # If no matching image, try to find any png
            if not img_path.exists():
                pngs = list(char_dir.glob("*.png"))
                if pngs:
                    img_path = pngs[0]
                else:
                    continue

            ref_scale = 1.0
            if yml_path.exists():
                try:
                    with yml_path.open("r", encoding="utf-8") as f:
                        meta = yaml.safe_load(f) or {}
                    ref_scale = float(meta.get("scale", 1.0))
                except Exception:
                    pass

            try:
                img = Image.open(img_path).convert("RGBA")
                self._references[name] = {"image": img, "scale": ref_scale}
            except Exception:
                pass

    def _on_ref_change(self, name: str) -> None:
        """Handle reference selection change."""
        self._ref_var.set(name)
        self._redraw()

    def _update_slider_labels(self) -> None:
        """Update scale/height labels without redrawing canvases (called while dragging)."""
        self._scale_label.configure(text=f"{self._scale_var.get():.2f}")
        self._height_label.configure(text=str(self._height_var.get()))

    def _redraw(self, *args) -> None:
        """Redraw both canvases."""
        self._ref_canvas.delete("all")
        self._user_canvas.delete("all")

        current_scale = self._scale_var.get()
        self._scale_label.configure(text=f"{current_scale:.2f}")

        # Update height label
        height_val = self._height_var.get()
        self._height_label.configure(text=str(height_val))

        # Get reference
        ref_name = self._ref_var.get()
        if not ref_name or ref_name not in self._references:
            return

        r_meta = self._references[ref_name]
        rimg = r_meta["image"]
        r_scale = r_meta["scale"]

        # Calculate engine dimensions
        r_engine_w = rimg.width * r_scale
        r_engine_h = rimg.height * r_scale

        # Apply height crop to user image (top N pixels only)
        u_img_cropped = None
        if self._user_img:
            effective_h = min(height_val, self._user_img.height)
            if effective_h < self._user_img.height:
                u_img_cropped = self._user_img.crop((0, 0, self._user_img.width, effective_h))
            else:
                u_img_cropped = self._user_img
            u_engine_w = u_img_cropped.width * current_scale
            u_engine_h = u_img_cropped.height * current_scale
        else:
            u_engine_w = u_engine_h = 0

        # Calculate view scale to fit both in canvases
        max_w = max(r_engine_w, u_engine_w, 1)
        max_h = max(r_engine_h, u_engine_h, 1)
        view_scale = min(self._canv_w / max_w, self._canv_h / max_h, 1.0)

        # Draw reference
        r_disp_w = max(1, int(r_engine_w * view_scale))
        r_disp_h = max(1, int(r_engine_h * view_scale))
        r_resized = rimg.resize((r_disp_w, r_disp_h), Image.LANCZOS)
        self._img_refs["ref"] = ImageTk.PhotoImage(r_resized)
        self._ref_canvas.create_image(
            self._canv_w // 2, self._canv_h,
            anchor="s",
            image=self._img_refs["ref"]
        )

        # Draw user (with height crop applied)
        if u_img_cropped:
            u_disp_w = max(1, int(u_engine_w * view_scale))
            u_disp_h = max(1, int(u_engine_h * view_scale))
            u_resized = u_img_cropped.resize((u_disp_w, u_disp_h), Image.LANCZOS)
            self._img_refs["usr"] = ImageTk.PhotoImage(u_resized)
            self._user_canvas.create_image(
                self._canv_w // 2, self._canv_h,
                anchor="s",
                image=self._img_refs["usr"]
            )

            # Draw eye line across BOTH canvases if available
            # This helps compare eye levels between reference and user character
            if self.state.eye_line_ratio is not None and self._user_img:
                # eye_line_ratio is relative to the FULL image height.
                # When height slider crops the image, convert to cropped coordinates.
                full_h = self._user_img.height
                eye_pixel = self.state.eye_line_ratio * full_h
                cropped_h = u_img_cropped.height if u_img_cropped else full_h
                # Only draw if the eye line is within the cropped region
                if eye_pixel <= cropped_h:
                    img_top = self._canv_h - u_disp_h
                    y_inside = int(u_disp_h * (eye_pixel / cropped_h))
                    y_canvas = img_top + y_inside
                # Draw on user canvas (right)
                self._user_canvas.create_line(
                    0, y_canvas, self._canv_w, y_canvas,
                    fill=LINE_COLOR, width=2
                )
                # Draw on reference canvas (left) at same Y for comparison
                self._ref_canvas.create_line(
                    0, y_canvas, self._canv_w, y_canvas,
                    fill=LINE_COLOR, width=2
                )

    def validate(self) -> bool:
        """Save scale and validate."""
        scale_val = float(self._scale_var.get())
        apply_val = bool(self._apply_scale_var.get())
        log_info(f"ScaleStep.validate(): scale_factor={scale_val}, apply_scale_to_images={apply_val}")
        self.state.scale_factor = scale_val
        self.state.apply_scale_to_images = apply_val

        # Save image_height only if user cropped (height < full image height)
        # image_height must be scaled to match in-game dimensions (scale is applied to the image first)
        height_val = int(self._height_var.get())
        if hasattr(self, "_user_img") and self._user_img and height_val < self._user_img.height:
            scaled_height = int(height_val * scale_val)
            self.state.image_height = scaled_height
            log_info(f"ScaleStep.validate(): image_height={scaled_height} (raw={height_val} * scale={scale_val:.2f})")
        else:
            self.state.image_height = None

        return True


class SummaryStep(WizardStep):
    """
    Step 10: Final Summary.

    Shows completion status and output location.
    """

    STEP_ID = "summary"
    STEP_TITLE = "Complete"
    STEP_NUMBER = 10
    STEP_TIP = (
        "All done! Use the buttons below to open the output folder, "
        "preview in-game, or upload to the sprite database."
    )
    STEP_HELP = """Character Complete!

Your character has been created and all files are saved.

FILES CREATED
Your character folder contains:

character.yml
Configuration file with name, voice, scale, eye line, and pose mappings. Used by visual novel engines to display the character correctly.

Pose Folders (a/, b/, etc.)
Each outfit becomes a "pose" folder containing:
- The outfit image
- A faces/ subfolder with all expressions

Expression Sheets
Automatically generated sprite sheets combining all expressions for each pose. These are optimized for game engines.

How-To-Use.txt
A guide with instructions for using your character in Student Transfer, including Ren'Py code snippets and file placement steps.

WHAT TO DO NEXT

Open Sprite Tester
Launches an interactive preview tool. You can:
- View all poses and expressions
- Test different backgrounds
- See how the character will look in-game

Open Output Folder
Opens the character folder in your file explorer. From here you can:
- Copy files to your game project
- Review individual images
- Make manual adjustments if needed

Upload to Database
Uploads your character to the community sprite database. On first use,
you'll be prompted for a display name (saved for future uploads).

USING IN STUDENT TRANSFER
Copy the entire character folder into your scenario's characters folder:
  game/scenario/<your_scenario>/characters/

MAKING CHANGES
If you need to regenerate or modify anything, you'll need to run the wizard again. The existing character folder will be preserved (a new one is created with a unique name).

Click Finish to close the wizard."""

    def __init__(self, wizard, state: WizardState):
        super().__init__(wizard, state)
        self._summary_frame: Optional[tk.Frame] = None
        self._guide_text: Optional[tk.Text] = None
        self._actions_frame: Optional[tk.Frame] = None
        self._finalized = False  # Track if finalization has already run
        self._uploaded = False   # Track if upload has been done this session

    def build_ui(self, parent: tk.Frame) -> None:
        parent.configure(bg=BG_COLOR)

        # Title row with checkmark
        title_row = tk.Frame(parent, bg=BG_COLOR)
        title_row.pack(fill="x", pady=(0, 16))

        tk.Label(
            title_row,
            text="✓ ",
            bg=BG_COLOR,
            fg=SUCCESS_COLOR,
            font=PAGE_TITLE_FONT,
        ).pack(side="left", padx=(40, 0))

        tk.Label(
            title_row,
            text="Character Creation Complete!",
            bg=BG_COLOR,
            fg=ACCENT_COLOR,
            font=PAGE_TITLE_FONT,
        ).pack(side="left")

        self._build_tip_bar(parent)

        # Three-column layout
        content_frame = tk.Frame(parent, bg=BG_COLOR)
        content_frame.pack(fill="both", expand=True, padx=20, pady=(8, 0))

        # Left column - Summary info
        left_col = tk.Frame(content_frame, bg=BG_COLOR, width=320)
        left_col.pack(side="left", fill="y", padx=(0, 8))
        left_col.pack_propagate(False)

        self._summary_frame = tk.Frame(left_col, bg=CARD_BG, padx=16, pady=12)
        self._summary_frame.pack(fill="both", expand=True)

        # Middle column - ST Usage Guide (scrollable)
        mid_col = tk.Frame(content_frame, bg=BG_COLOR)
        mid_col.pack(side="left", fill="both", expand=True, padx=8)

        guide_card = tk.Frame(mid_col, bg=CARD_BG, padx=16, pady=12)
        guide_card.pack(fill="both", expand=True)

        tk.Label(
            guide_card,
            text="Using in Student Transfer",
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=SECTION_FONT,
        ).pack(anchor="w", pady=(0, 2))

        tk.Label(
            guide_card,
            text="Also saved as How-To-Use.txt in your character folder.",
            bg=CARD_BG,
            fg=TEXT_SECONDARY,
            font=("", 8),
        ).pack(anchor="w", pady=(0, 6))

        guide_inner = tk.Frame(guide_card, bg=CARD_BG)
        guide_inner.pack(fill="both", expand=True)

        self._guide_text = tk.Text(
            guide_inner,
            wrap="word",
            bg="#1E1E1E",
            fg=TEXT_SECONDARY,
            font=("Consolas", 9),
            relief="flat",
            highlightthickness=1,
            highlightbackground="#444444",
            padx=10,
            pady=10,
            state="disabled",
        )
        guide_scroll = ttk.Scrollbar(guide_inner, orient="vertical", command=self._guide_text.yview)
        self._guide_text.configure(yscrollcommand=guide_scroll.set)
        self._guide_text.pack(side="left", fill="both", expand=True)
        guide_scroll.pack(side="right", fill="y")

        copy_btn = create_secondary_button(
            guide_card, "Copy to Clipboard", self._copy_guide_to_clipboard, width=16
        )
        copy_btn.pack(anchor="e", pady=(8, 0))

        # Right column - Action buttons
        right_col = tk.Frame(content_frame, bg=BG_COLOR, width=180)
        right_col.pack(side="right", fill="y", padx=(8, 0))
        right_col.pack_propagate(False)

        self._actions_frame = tk.Frame(right_col, bg=CARD_BG, padx=16, pady=12)
        self._actions_frame.pack(fill="both", expand=True)

    def on_leave(self) -> None:
        """Reset finalized flag when navigating back so re-entry re-finalizes."""
        self._finalized = False

    def on_enter(self) -> None:
        """Populate summary when step becomes active and finalize character."""
        # If already finalized (user went back and came forward), just show summary
        if self._finalized:
            self._populate_summary()
            return

        # Show loading and disable nav buttons during finalization
        self.show_loading("Finalizing character...")
        self.wizard._back_btn.configure(state="disabled")
        self.wizard._next_btn.configure(state="disabled")

        def do_finalize():
            try:
                self._finalize_character()
                self.schedule_callback(self._on_finalization_complete)
            except Exception as e:
                msg = str(e)
                self.schedule_callback(lambda m=msg: self._on_finalization_error(m))

        import threading
        threading.Thread(target=do_finalize, daemon=True).start()

    def _update_progress(self, message: str) -> None:
        """Thread-safe progress update during finalization."""
        self.schedule_callback(lambda: self.show_loading(message))

    def _on_finalization_complete(self) -> None:
        """Handle finalization completion on the main thread."""
        self.hide_loading()
        self.wizard._back_btn.configure(state="normal")
        self.wizard._next_btn.configure(state="normal")
        self._populate_summary()

    def _on_finalization_error(self, error_msg: str) -> None:
        """Handle finalization error on the main thread."""
        self.hide_loading()
        self.wizard._back_btn.configure(state="normal")
        self.wizard._next_btn.configure(state="normal")
        log_error(f"FINALIZE: Error during finalization: {error_msg}")
        show_error_dialog(
            self.wizard.root,
            "Finalization Error",
            f"An error occurred during finalization:\n\n{error_msg}\n\n"
            f"Your generated files are still in the character folder."
        )

    def _populate_summary(self) -> None:
        """Build the summary UI with character info and action buttons."""
        # Clear existing summary content
        for widget in self._summary_frame.winfo_children():
            widget.destroy()

        # Clear existing action buttons
        for widget in self._actions_frame.winfo_children():
            widget.destroy()

        # === LEFT COLUMN: Summary Info ===
        if self.state.is_adding_to_existing:
            tk.Label(
                self._summary_frame,
                text="Content Added Summary",
                bg=CARD_BG,
                fg=TEXT_COLOR,
                font=SECTION_FONT,
            ).pack(anchor="w", pady=(0, 12))

            # Character info
            self._add_row("Character:", self.state.display_name)

            # New outfits added
            new_outfit_count = len(self.state.generated_outfit_keys) if self.state.generated_outfit_keys else 0
            if new_outfit_count > 0:
                self._add_row("New Outfits Added:", str(new_outfit_count))

            # Existing outfits extended
            if self.state.existing_outfits_to_extend:
                extended_count = len(self.state.existing_outfits_to_extend)
                total_expr = sum(len(exprs) for exprs in self.state.existing_outfits_to_extend.values())
                self._add_row("Outfits Extended:", str(extended_count))
                self._add_row("New Expressions Added:", str(total_expr))

            # Scale info (if applied)
            if self.state.scale_factor and self.state.scale_factor != 1.0:
                self._add_row("Scale Applied:", f"{self.state.scale_factor:.2f}")

            # Output location
            if self.state.character_folder:
                self._add_row("Character Folder:", str(self.state.character_folder))
        else:
            # Normal mode summary
            tk.Label(
                self._summary_frame,
                text="Character Summary",
                bg=CARD_BG,
                fg=TEXT_COLOR,
                font=SECTION_FONT,
            ).pack(anchor="w", pady=(0, 12))

            # Character info
            self._add_row("Character Name:", self.state.display_name)
            self._add_row("Voice:", self.state.voice.capitalize())
            self._add_row("Archetype:", self.state.archetype_label)

            # Generation stats - use generated_outfit_keys for accurate count
            # (includes only outfits that succeeded, already includes base if applicable)
            outfit_count = len(self.state.generated_outfit_keys) if self.state.generated_outfit_keys else 0
            expr_count = len(self.state.expressions_sequence)
            self._add_row("Outfits Generated:", str(outfit_count))
            self._add_row("Expressions per Outfit:", str(expr_count))

            # Scale info
            if self.state.scale_factor:
                self._add_row("Scale:", f"{self.state.scale_factor:.2f}")

            # Name/Hair color with swatch
            if self.state.name_color:
                self._add_color_row("Name Color:", self.state.name_color)

            # Output location
            if self.state.character_folder:
                self._add_row("Output Folder:", str(self.state.character_folder))

        # Final message
        tk.Label(
            self._summary_frame,
            text="\nClick 'Finish' to close the wizard.",
            bg=CARD_BG,
            fg=TEXT_SECONDARY,
            font=BODY_FONT,
        ).pack(anchor="w", pady=(16, 0))

        # === RIGHT COLUMN: Action Buttons ===
        tk.Label(
            self._actions_frame,
            text="Actions",
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=SECTION_FONT,
        ).pack(anchor="w", pady=(0, 16))

        # Open Sprite Tester button
        create_primary_button(
            self._actions_frame,
            "Open Sprite Tester",
            self._open_sprite_tester,
            width=20,
        ).pack(pady=(0, 12))

        # Open Output Folder button
        create_secondary_button(
            self._actions_frame,
            "Open Output Folder",
            self._open_output_folder,
            width=20,
        ).pack(pady=(0, 12))

        # Upload to Database button
        create_secondary_button(
            self._actions_frame,
            "Upload to Database",
            self._upload_to_database,
            width=20,
        ).pack(pady=(0, 12))

        # === MIDDLE COLUMN: ST Usage Guide ===
        if self._guide_text:
            guide_content = self._build_usage_guide()
            self._guide_text.configure(state="normal")
            self._guide_text.delete("1.0", "end")
            self._guide_text.insert("1.0", guide_content)
            self._guide_text.configure(state="disabled")

    def _add_row(self, label: str, value: str) -> None:
        """Add a summary row."""
        row = tk.Frame(self._summary_frame, bg=CARD_BG)
        row.pack(fill="x", pady=4)

        tk.Label(
            row,
            text=label,
            bg=CARD_BG,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
            width=20,
            anchor="w",
        ).pack(side="left")

        tk.Label(
            row,
            text=value,
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=BODY_FONT,
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

    def _add_color_row(self, label: str, color: str) -> None:
        """Add a summary row with a color swatch."""
        row = tk.Frame(self._summary_frame, bg=CARD_BG)
        row.pack(fill="x", pady=4)

        tk.Label(
            row,
            text=label,
            bg=CARD_BG,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
            width=20,
            anchor="w",
        ).pack(side="left")

        # Color swatch
        swatch = tk.Label(
            row,
            text="   ",
            bg=color,
            width=3,
            relief="solid",
            borderwidth=1,
        )
        swatch.pack(side="left", padx=(0, 8))

        # Color hex value
        tk.Label(
            row,
            text=color,
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=BODY_FONT,
            anchor="w",
        ).pack(side="left")

    def _build_usage_guide(self) -> str:
        """Build the ST usage guide text dynamically from character data."""
        char_folder = self.state.character_folder
        name = char_folder.name if char_folder else "character"
        display = self.state.display_name or name

        # Discover all pose letters and their outfit names from the finalized folder
        all_pose_outfits = {}  # letter -> first outfit name (for AI poses, this is the only one)
        all_pose_outfit_lists = {}  # letter -> list of all outfit names (for standard poses with multiple)
        if char_folder and char_folder.exists():
            for d in sorted(char_folder.iterdir()):
                if d.is_dir() and len(d.name) == 1 and d.name.isalpha():
                    letter = d.name
                    outfit_names = []
                    outfits_dir = d / "outfits"
                    if outfits_dir.is_dir():
                        for item in sorted(outfits_dir.iterdir()):
                            if item.is_file() and item.suffix.lower() in ('.png', '.webp'):
                                outfit_names.append(item.stem)
                            elif item.is_dir():
                                outfit_names.append(item.name)
                    all_pose_outfits[letter] = outfit_names[0] if outfit_names else letter
                    all_pose_outfit_lists[letter] = outfit_names if outfit_names else [letter]

        # Read sprite_creator_poses from character.yml to distinguish SC vs original poses
        sc_poses = set()
        yml_path = char_folder / "character.yml" if char_folder else None
        if yml_path and yml_path.exists():
            try:
                with yml_path.open("r", encoding="utf-8") as f:
                    char_data = yaml.safe_load(f) or {}
                sc_poses = set(char_data.get("sprite_creator_poses", []))
            except Exception:
                pass

        # If no SC poses recorded (shouldn't happen), treat all as SC
        if not sc_poses:
            sc_poses = set(all_pose_outfits.keys())

        # Split into original ST poses and AI-generated poses
        original_poses = {k: v for k, v in all_pose_outfits.items() if k not in sc_poses}
        ai_poses = {k: v for k, v in all_pose_outfits.items() if k in sc_poses}

        first_ai_letter = list(ai_poses.keys())[0] if ai_poses else "a"
        expressions = self.state.expressions_sequence or []

        lines = []
        lines.append(f'USING "{display}" IN STUDENT TRANSFER')
        lines.append("=" * len(lines[0]))
        lines.append("")
        lines.append(f"Code name: {name}")
        lines.append("")

        # Pose/Outfit reference table
        lines.append("POSE & OUTFIT REFERENCE")
        lines.append("-" * 40)
        for letter in sorted(all_pose_outfits.keys()):
            outfits = all_pose_outfit_lists.get(letter, [])
            is_ai = letter in sc_poses
            tag = " (AI)" if is_ai else ""
            if len(outfits) == 1:
                lines.append(f"  Pose {letter} = {outfits[0]}{tag}")
            else:
                outfit_str = ", ".join(outfits)
                lines.append(f"  Pose {letter} = {outfit_str}{tag}")
        lines.append("")

        # Setup (only for new characters, not add-to-existing)
        if not original_poses:
            lines.append("SETUP")
            lines.append("-" * 40)
            lines.append(f'Copy the "{name}" folder into your scenario\'s characters folder:')
            lines.append(f"  game/scenario/<your_scenario>/characters/")
            lines.append("")

        # Explain how AI sprites differ from standard ST
        if original_poses and ai_poses:
            # Mixed character: has both standard and AI poses
            lines.append("STANDARD VS AI POSES")
            lines.append("-" * 40)
            orig_range = ", ".join(sorted(original_poses.keys()))
            ai_range = ", ".join(sorted(ai_poses.keys()))
            lines.append(f"This character has both standard ST poses")
            lines.append(f"({orig_range}) and AI-generated poses ({ai_range}).")
            lines.append("")
            lines.append("With standard ST sprites, the body, outfit, and")
            lines.append("face are separate layers. One pose can have many")
            lines.append("outfits, and 'outfit' swaps the clothing layer.")
            lines.append("")
            lines.append("With AI sprites, each expression image contains")
            lines.append("the full character (body + outfit + face all in")
            lines.append("one). Each outfit gets its own pose letter with")
            lines.append("its own set of expressions.")
            lines.append("")
            lines.append("The key difference when switching between them:")
            lines.append("With standard poses, you can stay on the same")
            lines.append("pose letter and just use 'outfit' to change")
            lines.append("clothes. With AI poses, changing outfit means")
            lines.append("changing the pose letter too. You should still")
            lines.append("use the 'outfit' command either way — see the")
            lines.append("examples below.")
            lines.append("")
        elif len(ai_poses) > 0:
            # Pure AI character
            lines.append("HOW AI SPRITES WORK")
            lines.append("-" * 40)
            lines.append("With standard ST sprites, the body, outfit, and")
            lines.append("face are separate layers. One pose can have many")
            lines.append("outfits, and 'outfit' swaps the clothing layer.")
            lines.append("")
            lines.append("With AI sprites, each expression image contains")
            lines.append("the full character (body + outfit + face all in")
            lines.append("one). Each outfit gets its own pose letter with")
            lines.append("its own set of expressions.")
            lines.append("")
            lines.append("You use them the same way as regular ST sprites —")
            lines.append("show, outfit, and expression commands all work.")
            lines.append("Just remember: to change outfit, you change the")
            lines.append("pose letter too. See the examples below.")
            lines.append("")

        # Show
        first_ai_outfit = list(ai_poses.values())[0] if ai_poses else "original"
        lines.append("SHOWING THE CHARACTER")
        lines.append("-" * 40)
        lines.append(f"  show {name} {first_ai_letter}_0 at center")
        lines.append(f"  outfit {first_ai_outfit}")
        lines.append(f"  with dissolve")
        lines.append("")

        # Expressions
        if expressions:
            lines.append("EXPRESSIONS")
            lines.append("-" * 40)
            lines.append("Change the number to change the expression:")
            for i, (key, desc) in enumerate(expressions):
                lines.append(f"  show {name} {first_ai_letter}_{i}    # {desc}")
            lines.append("")

        # Outfits
        if len(ai_poses) > 1:
            lines.append("CHANGING OUTFITS")
            lines.append("-" * 40)
            lines.append("To change outfits, change the pose letter and")
            lines.append("set the outfit for that pose:")
            lines.append("")
            for letter, outfit_name in ai_poses.items():
                lines.append(f"  show {name} {letter}_0")
                lines.append(f"  outfit {outfit_name}")
                lines.append("")
            lines.append("Each outfit has its own set of expressions,")
            lines.append("so expression numbers work the same across")
            lines.append("all outfits (0 = neutral, 1 = happy, etc.).")
            lines.append("")
            # Mixed character: show example of switching between standard and AI
            if original_poses:
                first_orig = list(original_poses.keys())[0]
                lines.append("SWITCHING BETWEEN STANDARD AND AI OUTFITS")
                lines.append("-" * 40)
                lines.append("Standard pose — stay on the same letter,")
                lines.append("just change the outfit:")
                lines.append(f"  show {name} {first_orig}_0")
                lines.append(f"  outfit uniform")
                lines.append(f"  # later...")
                lines.append(f"  outfit casual")
                lines.append("")
                first_ai_key = list(ai_poses.keys())[0]
                first_ai_name = list(ai_poses.values())[0]
                lines.append("AI pose — change the letter AND the outfit:")
                lines.append(f"  show {name} {first_ai_key}_0")
                lines.append(f"  outfit {first_ai_name}")
                if len(ai_poses) > 1:
                    second_key = list(ai_poses.keys())[1]
                    second_name = list(ai_poses.values())[1]
                    lines.append(f"  # later...")
                    lines.append(f"  show {name} {second_key}_0")
                    lines.append(f"  outfit {second_name}")
                lines.append("")
        elif len(ai_poses) == 1:
            lines.append("OUTFITS")
            lines.append("-" * 40)
            letter, outfit_name = next(iter(ai_poses.items()))
            lines.append(f"This character has one AI outfit ({outfit_name}).")
            lines.append(f"Set it with:")
            lines.append(f"  outfit {outfit_name}")
            lines.append("")

        # Positioning
        lines.append("POSITIONING")
        lines.append("-" * 40)
        lines.append(f"  show {name} {first_ai_letter}_0 at left")
        lines.append(f"  show {name} {first_ai_letter}_0 at centerleft")
        lines.append(f"  show {name} {first_ai_letter}_0 at center")
        lines.append(f"  show {name} {first_ai_letter}_0 at centerright")
        lines.append(f"  show {name} {first_ai_letter}_0 at right")
        lines.append("")

        # Facing direction
        lines.append("FACING DIRECTION")
        lines.append("-" * 40)
        lines.append(f"  show {name} {first_ai_letter}_0 at center, faceleft")
        lines.append(f"  show {name} {first_ai_letter}_0 at centerright, faceright")
        lines.append("")

        # Hiding
        lines.append("HIDING")
        lines.append("-" * 40)
        lines.append(f"  hide {name}")
        lines.append(f"  with dissolve")
        lines.append("")

        # Animated entrance
        lines.append("ANIMATED ENTRANCE")
        lines.append("-" * 40)
        lines.append(f"  show {name} {first_ai_letter}_0 at centerleft")
        lines.append(f"  with easeinleft")
        lines.append("")

        # showChar shorthand
        lines.append("showChar SHORTHAND")
        lines.append("-" * 40)
        lines.append("Instead of remembering pose letters and expression")
        lines.append("numbers, you can use the showChar command with")
        lines.append("emotion names:")
        lines.append("")
        lines.append(f"  showChar {name} happy at center with dissolve")
        lines.append(f"  showChar {name} sad at left")
        lines.append(f"  showChar {name} neutral")
        lines.append("")
        lines.append("showChar automatically picks the right pose letter")
        lines.append("based on the current outfit. Set the outfit first:")
        lines.append("")
        lines.append(f"  outfit {name} casual")
        lines.append(f"  showChar {name} happy at center")
        lines.append("")
        lines.append("You can omit the emotion to keep the current")
        lines.append("expression and just move or re-show the character:")
        lines.append("")
        lines.append(f"  showChar {name} at left with dissolve")
        lines.append(f"  showChar {name} with exchange")
        lines.append("")
        lines.append("Available emotions:")
        # Import here to avoid circular imports at module level
        from ...processing.showchar_generator import EMOTION_NAMES
        for i, ename in enumerate(EMOTION_NAMES):
            if i < len(expressions):
                lines.append(f"  {i:>2} = {ename}")
        lines.append("")

        return "\n".join(lines)

    def _write_usage_guide_file(self) -> None:
        """Write the ST usage guide to a How-To-Use.txt file in the character folder."""
        char_folder = self.state.character_folder
        if not char_folder or not char_folder.exists():
            return

        try:
            guide_content = self._build_usage_guide()
            guide_path = char_folder / "How-To-Use.txt"
            guide_path.write_text(guide_content, encoding="utf-8")
            print(f"[INFO] Saved How-To-Use.txt to {guide_path}")
        except Exception as e:
            print(f"[WARN] Failed to write How-To-Use.txt: {e}")

    def _copy_guide_to_clipboard(self) -> None:
        """Copy the ST usage guide text to the clipboard."""
        if self._guide_text:
            text = self._guide_text.get("1.0", "end-1c")
            if text.strip():
                self.wizard.root.clipboard_clear()
                self.wizard.root.clipboard_append(text)

    def _open_sprite_tester(self) -> None:
        """Launch the sprite tester for this character."""
        if not self.state.character_folder:
            messagebox.showerror("Error", "No character folder available.")
            return

        try:
            from tools.tester import launch_sprite_tester
            launch_sprite_tester(self.state.character_folder)
        except Exception as e:
            show_error_dialog(self.parent, "Error", f"Failed to launch sprite tester:\n{e}")

    def _open_output_folder(self) -> None:
        """Open the enclosing folder (parent of character folder) in file explorer."""
        if not self.state.character_folder:
            messagebox.showerror("Error", "No character folder available.")
            return

        # Open the parent folder so user can see the character folder from outside
        folder_path = self.state.character_folder.parent
        if not folder_path.exists():
            show_error_dialog(self.parent, "Error", f"Folder not found:\n{folder_path}")
            return

        try:
            import subprocess
            import platform

            print(f"[DEBUG] Opening folder: {folder_path}")

            if platform.system() == "Windows":
                # Use explorer.exe explicitly instead of os.startfile() to avoid
                # unexpected behavior with file associations
                subprocess.Popen(["explorer", str(folder_path)])
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(["open", str(folder_path)], check=False)
            else:  # Linux
                subprocess.run(["xdg-open", str(folder_path)], check=False)
        except Exception as e:
            show_error_dialog(self.parent, "Error", f"Failed to open folder:\n{e}")

    def _upload_to_database(self) -> None:
        """Zip the character folder and upload it to the SpriteBot database."""
        if self._uploaded:
            messagebox.showwarning(
                "Already Uploaded",
                "This character has already been uploaded this session."
            )
            return

        if not self.state.character_folder or not self.state.character_folder.exists():
            messagebox.showerror("Error", "No character folder available.")
            return

        from ...config import load_upload_username, save_upload_username

        # Check for saved username; prompt if not set
        username = load_upload_username()
        if not username:
            username = self._prompt_for_username()
            if not username:
                return  # User cancelled

        # Confirm upload
        char_name = self.state.character_folder.name
        if not messagebox.askyesno(
            "Upload to Database",
            f"Upload \"{char_name}\" to the SpriteBot database as \"{username}\"?",
        ):
            return

        # Check for duplicate before uploading
        self._upload_btn_state("disabled")
        self.show_loading("Checking for duplicates...")

        import threading
        threading.Thread(
            target=self._check_and_upload, args=(username, char_name), daemon=True
        ).start()

    def _check_and_upload(self, username: str, char_name: str) -> None:
        """Check for duplicates, then zip and upload (runs in background thread)."""
        from ...api.uploader import check_duplicate

        on_conflict = None

        success, exists = check_duplicate(char_name, username)
        if success and exists:
            # Duplicate found — ask user on main thread
            result = [None]
            import threading
            event = threading.Event()

            def ask_user():
                answer = messagebox.askyesnocancel(
                    "Character Already Exists",
                    f"A character named \"{char_name}\" by \"{username}\" "
                    f"already exists in the database.\n\n"
                    f"Replace the existing character?\n\n"
                    f"Yes = Replace existing\n"
                    f"No = Keep both (rename)\n"
                    f"Cancel = Abort upload",
                )
                result[0] = answer
                event.set()

            self.schedule_callback(ask_user)
            event.wait()

            if result[0] is None:
                # User cancelled
                self.schedule_callback(lambda: self.hide_loading())
                self.schedule_callback(lambda: self._upload_btn_state("normal"))
                return
            elif result[0]:
                on_conflict = "replace"
            else:
                on_conflict = "rename"

        # Proceed with upload
        self.schedule_callback(lambda: self.show_loading("Zipping character folder..."))
        self._do_upload(username, on_conflict)

    def _prompt_for_username(self) -> Optional[str]:
        """Show a dialog to enter an upload username. Returns None if cancelled."""
        from ...config import save_upload_username

        dialog = tk.Toplevel(self.wizard.root)
        dialog.title("Set Upload Username")
        dialog.configure(bg=BG_COLOR)
        dialog.resizable(False, False)
        dialog.grab_set()

        # Center on parent
        dialog.update_idletasks()
        pw = self.wizard.root
        x = pw.winfo_x() + (pw.winfo_width() // 2) - 150
        y = pw.winfo_y() + (pw.winfo_height() // 2) - 60
        dialog.geometry(f"300x140+{x}+{y}")

        tk.Label(
            dialog, text="Enter your display name for uploads:",
            bg=BG_COLOR, fg=TEXT_COLOR, font=BODY_FONT,
        ).pack(pady=(16, 8), padx=16)

        entry = tk.Entry(dialog, font=BODY_FONT, width=30)
        entry.pack(padx=16)
        entry.focus_set()

        result = [None]

        def on_ok(event=None):
            val = entry.get().strip()
            if val:
                save_upload_username(val)
                result[0] = val
                dialog.destroy()

        btn_row = tk.Frame(dialog, bg=BG_COLOR)
        btn_row.pack(pady=(12, 0))
        create_primary_button(btn_row, "OK", on_ok, width=8).pack(side="left", padx=4)
        create_secondary_button(btn_row, "Cancel", dialog.destroy, width=8).pack(side="left", padx=4)
        entry.bind("<Return>", on_ok)

        dialog.wait_window()
        return result[0]

    def _upload_btn_state(self, state: str) -> None:
        """Enable or disable the upload button if it exists."""
        if self._actions_frame:
            for child in self._actions_frame.winfo_children():
                if isinstance(child, tk.Button) and child.cget("text") == "Upload to Database":
                    child.configure(state=state)
                    if state == "disabled":
                        child.configure(text="Uploading...")
                    else:
                        child.configure(text="Upload to Database")
                    break

    def _do_upload(self, username: str, on_conflict: Optional[str] = None) -> None:
        """Zip and upload the character folder (runs in background thread)."""
        import tempfile
        import zipfile

        char_folder = self.state.character_folder
        zip_path = None
        try:
            # Step 1: Zip
            tmp = tempfile.NamedTemporaryFile(
                suffix=".zip", prefix=f"{char_folder.name}_", delete=False
            )
            zip_path = Path(tmp.name)
            tmp.close()

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for file in char_folder.rglob("*"):
                    if file.is_file():
                        arcname = f"{char_folder.name}/{file.relative_to(char_folder)}"
                        zf.write(file, arcname)

            # Step 2: Upload
            self.schedule_callback(lambda: self.show_loading("Uploading to database..."))

            from ...api.uploader import upload_character_zip
            success, message = upload_character_zip(zip_path, username, on_conflict)

            self.schedule_callback(lambda: self._upload_finished(success, message))

        except Exception as e:
            self.schedule_callback(
                lambda: self._upload_finished(False, f"Failed to create zip: {e}")
            )
        finally:
            if zip_path and zip_path.exists():
                try:
                    zip_path.unlink()
                except Exception:
                    pass

    def _upload_finished(self, success: bool, message: str) -> None:
        """Handle upload completion (called on main thread)."""
        self.hide_loading()
        self._upload_btn_state("normal")
        if success:
            self._uploaded = True
            messagebox.showinfo("Upload Complete", message)
        else:
            messagebox.showerror("Upload Failed", message)

    def _on_finish(self) -> None:
        """Open the output folder and close the application."""
        # Open the folder first
        self._open_output_folder()

        # Close the application
        try:
            # Get the root window and destroy it
            root = self.parent.winfo_toplevel()
            root.quit()
            root.destroy()
        except Exception:
            # Fallback: just exit
            sys.exit(0)

    def _apply_scale_to_images(self, char_dir: Path, pose_letters: list, scale: float) -> int:
        """
        Scale down all outfit and face images using LANCZOS resampling.

        Args:
            char_dir: Character directory
            pose_letters: List of pose letters (a, b, c, etc.)
            scale: Scale factor (e.g., 0.8 = 80% of original size)

        Returns:
            Number of images scaled
        """
        scaled_count = 0
        log_info(f"_apply_scale_to_images: char_dir={char_dir}, pose_letters={pose_letters}, scale={scale}")

        for pose_letter in pose_letters:
            pose_dir = char_dir / pose_letter
            log_info(f"  Processing pose '{pose_letter}': {pose_dir}")

            # Scale outfits
            outfits_dir = pose_dir / "outfits"
            if outfits_dir.exists():
                outfit_files = [f for f in outfits_dir.iterdir() if f.suffix.lower() in ('.png', '.webp')]
                log_info(f"    Found {len(outfit_files)} outfit images in {outfits_dir}")
                for img_file in outfit_files:
                    if self._scale_image_file(img_file, scale):
                        scaled_count += 1
            else:
                log_info(f"    No outfits dir: {outfits_dir}")

            # Scale faces
            faces_dir = pose_dir / "faces"
            if faces_dir.exists():
                for face_subdir in faces_dir.iterdir():
                    if face_subdir.is_dir():
                        face_files = [f for f in face_subdir.iterdir() if f.suffix.lower() in ('.png', '.webp')]
                        log_info(f"    Found {len(face_files)} face images in {face_subdir}")
                        for img_file in face_files:
                            if self._scale_image_file(img_file, scale):
                                scaled_count += 1
            else:
                log_info(f"    No faces dir: {faces_dir}")

        return scaled_count

    def _scale_image_file(self, img_path: Path, scale: float) -> bool:
        """
        Scale a single image file using LANCZOS resampling.

        Args:
            img_path: Path to image file
            scale: Scale factor

        Returns:
            True if successful, False otherwise
        """
        try:
            img = Image.open(img_path).convert("RGBA")
            new_w = int(img.width * scale)
            new_h = int(img.height * scale)

            # Use LANCZOS for highest quality downscaling
            scaled_img = img.resize((new_w, new_h), Image.LANCZOS)

            # Save in original format
            if img_path.suffix.lower() == '.webp':
                scaled_img.save(img_path, format="WEBP", quality=95, method=6)
            else:
                scaled_img.save(img_path, format="PNG", compress_level=6, optimize=True)

            log_info(f"Scaled: {img_path.name} ({img.width}x{img.height} -> {new_w}x{new_h})")
            return True
        except Exception as e:
            log_error("Image scaling", f"Failed to scale {img_path.name}: {e}")
            return False

    def _finalize_character(self) -> None:
        """Finalize character: create character.yml and expression sheets."""
        from ...processing.pose_processor import flatten_pose_outfits_to_letter_poses, write_character_yml
        from ...processing import generate_expression_sheets_for_root
        import shutil

        # Skip if already finalized (user went back and came forward again)
        if self._finalized:
            log_info("Skipping finalization - already completed")
            return

        # Handle add-to-existing mode differently
        if self.state.is_adding_to_existing:
            self._finalize_add_to_existing()
            return

        if not self.state.character_folder:
            return

        char_dir = self.state.character_folder
        log_info(f"FINALIZE: mode=new, folder={char_dir}")

        try:
            # Flatten pose/outfit combinations into letter poses
            self._update_progress("Organizing pose structure...")
            print("[INFO] Flattening pose/outfit combinations into letter poses...")
            final_pose_letters = flatten_pose_outfits_to_letter_poses(
                char_dir, outfit_order=self.state.generated_outfit_keys
            )
            if not final_pose_letters:
                print("[WARN] Flattening produced no poses; using existing letter folders.")
                final_pose_letters = sorted(
                    [
                        p.name
                        for p in char_dir.iterdir()
                        if p.is_dir() and len(p.name) == 1 and p.name.isalpha()
                    ]
                )

            # Backup full-size 0.png for each pose BEFORE scaling
            # Stored externally so character folder stays clean for ST
            self._update_progress("Creating full-size backups...")
            original_size = None
            backup_id = generate_backup_id()
            self.state.backup_id = backup_id
            self._create_backups(char_dir, final_pose_letters, backup_id)

            # Capture original image size for reference
            for letter in final_pose_letters:
                face_path = char_dir / letter / "faces" / "face" / "0.png"
                if face_path.exists():
                    try:
                        img = Image.open(face_path)
                        original_size = list(img.size)
                        img.close()
                        break
                    except Exception:
                        pass

            # Apply scale to images if enabled (only scale DOWN, not up)
            final_scale = self.state.scale_factor or 1.0
            log_info(f"Scale check: apply_scale_to_images={self.state.apply_scale_to_images}, scale_factor={final_scale}")

            if self.state.apply_scale_to_images and final_scale < 1.0:
                self._update_progress("Scaling images...")
                log_info(f"Applying scale {final_scale} to all images (LANCZOS resampling)...")
                print(f"[INFO] Applying scale {final_scale} to all images (LANCZOS resampling)...")
                scaled_count = self._apply_scale_to_images(char_dir, final_pose_letters, final_scale)
                log_info(f"Scaled {scaled_count} images successfully")
                print(f"[INFO] Scaled {scaled_count} images")
                # After scaling, the images are at their final size, so scale becomes 1.0
                final_scale = 1.0
            else:
                if not self.state.apply_scale_to_images:
                    log_info("Skipping image scaling: checkbox not checked")
                elif final_scale >= 1.0:
                    log_info(f"Skipping image scaling: scale={final_scale} is >= 1.0 (only scale down)")

            # Build poses yaml
            pose_data = {"facing": "right"}
            if self.state.image_height:
                pose_data["image_height"] = self.state.image_height
            poses_yaml = {letter: dict(pose_data) for letter in final_pose_letters}

            # Write character.yml with values from wizard state
            self._update_progress("Writing character data...")
            # Include archetype and sprite_creator_poses for future add-to-character functionality
            yml_path = char_dir / "character.yml"
            write_character_yml(
                yml_path,
                self.state.display_name,
                self.state.voice,
                self.state.eye_line_ratio or 0.3,
                self.state.name_color or "#915f40",
                final_scale,
                poses_yaml,
                game=None,
                archetype=self.state.archetype_label or None,
                hair_length=self.state.hair_length or None,
                sprite_creator_poses=final_pose_letters,
                original_size=original_size,
                backup_id=backup_id,
            )
            print(f"[INFO] Created character.yml for {self.state.display_name}")

            # Save original.png (the cropped character image) for future reference
            if self.state.base_pose_path and self.state.base_pose_path.exists():
                base_dest = char_dir / "original.png"
                if not base_dest.exists():
                    shutil.copy2(self.state.base_pose_path, base_dest)
                    # Scale original.png to match other images if scaling was applied
                    if self.state.apply_scale_to_images and (self.state.scale_factor or 1.0) < 1.0:
                        self._scale_image_file(base_dest, self.state.scale_factor)
                    print(f"[INFO] Saved original.png to {base_dest}")

            # Generate expression sheets (will use scaled images if scaling was applied)
            self._update_progress("Generating expression sheets...")
            generate_expression_sheets_for_root(char_dir)
            print(f"[INFO] Generated expression sheets for {self.state.display_name}")

            # Generate showChar Ren'Py statement files
            self._update_progress("Generating showChar helper files...")
            from ...processing.showchar_generator import generate_showchar_files
            generate_showchar_files(char_dir)

            # Write How-To-Use.txt with ST usage instructions
            self._update_progress("Writing usage guide...")
            self._write_usage_guide_file()

            # Mark as finalized so we don't re-run if user goes back and forward
            self._finalized = True
            log_info(f"FINALIZE: Complete at {char_dir}")

        except Exception as e:
            log_error(f"FINALIZE: Error: {e}")
            print(f"[ERROR] Finalization error: {e}")
            import traceback
            traceback.print_exc()
            raise  # Let the threaded caller handle UI notification

    def _finalize_add_to_existing(self) -> None:
        """Finalize for add-to-existing mode: merge new content with existing character."""
        from ...processing.pose_processor import flatten_pose_outfits_to_letter_poses
        from ...processing import generate_expression_sheets_for_root
        import shutil

        existing_folder = self.state.existing_character_folder
        working_folder = self.state.character_folder

        if not existing_folder or not working_folder:
            log_error("Add-to-existing", "Missing folder paths")
            return

        # SAFETY: Verify we're not about to corrupt the existing folder
        if working_folder == existing_folder:
            log_error("Add-to-existing", "CRITICAL: working_folder == existing_folder! This would corrupt data.")
            print("[ERROR] Cannot finalize: working folder same as existing folder. Aborting.")
            return

        # Log folder paths for debugging
        log_info(f"FINALIZE: mode=add_existing, folder={existing_folder}")
        log_info(f"FINALIZE: working_folder={working_folder}")

        try:
            new_pose_letters = []

            # 1. Process NEW outfits (if any)
            has_new_outfits = (
                self.state.generated_outfit_keys
                and len(self.state.generated_outfit_keys) > 0
            )

            if has_new_outfits:
                self._update_progress("Organizing new outfits...")
                print("[INFO] Flattening new outfits...")
                # Flatten new outfits in working folder, starting from next available letter
                new_pose_letters = flatten_pose_outfits_to_letter_poses(
                    working_folder,
                    starting_letter=self.state.next_pose_letter,
                    outfit_order=self.state.generated_outfit_keys,
                )
                log_info(f"Created new poses: {new_pose_letters}")

                # Backup full-size 0.png BEFORE scaling (stored externally)
                self._update_progress("Creating full-size backups...")
                # Use existing backup_id or generate a new one
                backup_id = self.state.backup_id
                if not backup_id:
                    backup_id = self.state.existing_character_data.get('backup_id')
                if not backup_id:
                    backup_id = generate_backup_id()
                self.state.backup_id = backup_id
                self._create_backups(working_folder, new_pose_letters, backup_id)

                # Apply scale to new poses (always applied in add-to-existing mode)
                scale_factor = self.state.scale_factor or 1.0
                if scale_factor != 1.0:
                    self._update_progress("Scaling images...")
                    log_info(f"Applying scale {scale_factor} to new poses...")
                    self._apply_scale_to_images(working_folder, new_pose_letters, scale_factor)

                # Dimension safety net: compare new vs existing image sizes
                self._validate_dimensions(working_folder, new_pose_letters, existing_folder, scale_factor)

                # Copy new poses to existing character folder
                self._update_progress("Copying new outfits to character...")
                for pose_letter in new_pose_letters:
                    src_pose = working_folder / pose_letter
                    dest_pose = existing_folder / pose_letter
                    if src_pose.exists():
                        if dest_pose.exists():
                            shutil.rmtree(dest_pose)
                        shutil.copytree(src_pose, dest_pose)
                        log_info(f"Copied pose {pose_letter} to existing character")

                # Migrate legacy _backups from inside existing character folder to external storage
                legacy_backups = existing_folder / "_backups"
                if legacy_backups.exists():
                    log_info(f"Migrating legacy _backups to external storage...")
                    ext_dir = get_backup_dir(backup_id)
                    for item in legacy_backups.iterdir():
                        dest_item = ext_dir / item.name
                        if item.is_dir():
                            if not dest_item.exists():
                                shutil.copytree(item, dest_item)
                        else:
                            if not dest_item.exists():
                                dest_item.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(item, dest_item)
                    shutil.rmtree(legacy_backups)
                    log_info(f"Migrated legacy backups and removed _backups folder")

            # 2. Scale expressions for EXISTING outfits (they're already in place)
            if self.state.existing_outfits_to_extend:
                scale_factor = self.state.scale_factor or 1.0
                if scale_factor != 1.0:
                    for pose_letter, expr_keys in self.state.existing_outfits_to_extend.items():
                        faces_dir = existing_folder / pose_letter / "faces" / "face"
                        for expr_key in expr_keys:
                            for ext in [".png", ".webp"]:
                                expr_path = faces_dir / f"{expr_key}{ext}"
                                if expr_path.exists():
                                    self._scale_image_file(expr_path, scale_factor)
                                    break

            # 3. Save original.png to existing folder (if not already exists)
            if self.state.base_pose_path and self.state.base_pose_path.exists():
                base_dest = existing_folder / "original.png"
                if not base_dest.exists():
                    shutil.copy2(self.state.base_pose_path, base_dest)
                    scale_factor = self.state.scale_factor or 1.0
                    if scale_factor != 1.0:
                        self._scale_image_file(base_dest, scale_factor)
                    log_info(f"Saved original.png to {base_dest}")

            # 4. Update character.yml (merge, preserving existing values)
            self._update_progress("Writing character data...")
            self._merge_character_yml(existing_folder, new_pose_letters)

            # 5. Regenerate expression sheets for ALL affected poses
            # (existing poses that got new expressions + new poses)
            affected_poses = list(self.state.existing_outfits_to_extend.keys()) + new_pose_letters
            if affected_poses:
                self._update_progress("Generating expression sheets...")
                log_info(f"Regenerating expression sheets for poses: {affected_poses}")
                # Generate for the whole character (will cover all poses)
                generate_expression_sheets_for_root(existing_folder)

            # Generate showChar Ren'Py statement files
            self._update_progress("Generating showChar helper files...")
            from ...processing.showchar_generator import generate_showchar_files
            generate_showchar_files(existing_folder)

            # Update state to point to existing folder for summary display
            self.state.character_folder = existing_folder

            # Write How-To-Use.txt with ST usage instructions
            self._update_progress("Writing usage guide...")
            self._write_usage_guide_file()

            # Clean up temp working folder (it's no longer needed after merge)
            if working_folder != existing_folder and working_folder.exists():
                try:
                    shutil.rmtree(working_folder)
                    log_info(f"Cleaned up temp folder: {working_folder}")
                except Exception as cleanup_e:
                    log_error("Cleanup temp folder", str(cleanup_e))

            self._finalized = True
            log_info(f"FINALIZE: Complete at {existing_folder}")

        except Exception as e:
            log_error(f"FINALIZE: Error in add-to-existing: {e}")
            print(f"[ERROR] Add-to-existing finalization error: {e}")
            import traceback
            traceback.print_exc()
            raise  # Let the threaded caller handle UI notification

    def _create_backups(self, char_dir: Path, pose_letters: list, backup_id: str) -> None:
        """Backup full-size 0.png for each pose before scaling.

        Stores backups externally at ~/.sprite_creator/backups/<backup_id>/
        to keep character folders clean for ST game compatibility.
        """
        import shutil

        backups_dir = get_backup_dir(backup_id)
        backed_up = 0

        for letter in pose_letters:
            src = char_dir / letter / "faces" / "face" / "0.png"
            if not src.exists():
                src = char_dir / letter / "faces" / "face" / "0.webp"
            if src.exists():
                dest = backups_dir / letter / "faces" / "face" / src.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(src, dest)
                    backed_up += 1
                except Exception as e:
                    log_error("Backup", f"Failed to backup {src}: {e}")

        if backed_up > 0:
            log_info(f"Backed up {backed_up} full-size outfit images to {backups_dir}")
            print(f"[INFO] Backed up {backed_up} full-size outfit images")

    def _validate_dimensions(self, working_folder: Path, new_pose_letters: list, existing_folder: Path, scale_factor: float) -> None:
        """Validate that new images match existing character dimensions after scaling."""
        # Find first new image height
        new_h = None
        for pose_letter in new_pose_letters:
            face_dir = working_folder / pose_letter / "faces" / "face"
            if face_dir.is_dir():
                for ext in [".png", ".webp"]:
                    path = face_dir / f"0{ext}"
                    if path.exists():
                        try:
                            img = Image.open(path)
                            new_h = img.height
                            img.close()
                            break
                        except Exception:
                            pass
                if new_h:
                    break

        # Find first existing image height
        existing_h = None
        for pose_letter in "abcdefghijklmnopqrstuvwxyz":
            face_dir = existing_folder / pose_letter / "faces" / "face"
            if face_dir.is_dir():
                for ext in [".png", ".webp"]:
                    path = face_dir / f"0{ext}"
                    if path.exists():
                        try:
                            img = Image.open(path)
                            existing_h = img.height
                            img.close()
                            break
                        except Exception:
                            pass
                if existing_h:
                    break

        if new_h and existing_h:
            ratio = new_h / existing_h
            if abs(ratio - 1.0) > 0.05:
                log_info(f"DIMENSION WARNING: new_h={new_h}, existing_h={existing_h}, "
                         f"ratio={ratio:.3f}, scale_factor={scale_factor}")
                print(f"[WARN] New image height ({new_h}px) differs from existing ({existing_h}px) "
                      f"by {abs(ratio - 1.0)*100:.1f}%")

    def _merge_character_yml(self, char_dir: Path, new_pose_letters: list) -> None:
        """Update character.yml, preserving ALL existing data."""
        yml_path = char_dir / "character.yml"

        # Load existing data
        data = {}
        if yml_path.exists():
            try:
                with yml_path.open("r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            except Exception as e:
                log_error("Merge character.yml", f"Failed to read existing: {e}")

        # Add new poses (if any)
        if 'poses' not in data:
            data['poses'] = {}
        for letter in new_pose_letters:
            data['poses'][letter] = {'facing': 'right'}

        # Update voice if the user selected one (handles non-standard voices like "child")
        if self.state.voice in ("girl", "boy"):
            data['voice'] = self.state.voice

        # Add archetype if not present (for characters not originally made by this app)
        if 'archetype' not in data and self.state.archetype_label:
            data['archetype'] = self.state.archetype_label

        # Add new poses to sprite_creator_poses list
        # This tracks which poses were created by Sprite Creator (can add expressions to these)
        existing_sc_poses = data.get('sprite_creator_poses', [])
        if not isinstance(existing_sc_poses, list):
            existing_sc_poses = []
        # Add new poses that aren't already in the list
        for letter in new_pose_letters:
            if letter not in existing_sc_poses:
                existing_sc_poses.append(letter)
        data['sprite_creator_poses'] = sorted(existing_sc_poses)

        # Add backup_id for external backup storage
        if self.state.backup_id and 'backup_id' not in data:
            data['backup_id'] = self.state.backup_id

        # PRESERVE: All existing values (voice, eye_line, name_color, scale, display_name, archetype)
        # These are NOT overwritten with user selections

        # Write back
        try:
            with yml_path.open("w", encoding="utf-8") as f:
                yaml.dump(data, f, sort_keys=False, allow_unicode=True)
            log_info(f"Updated character.yml with {len(new_pose_letters)} new poses")
        except Exception as e:
            log_error("Merge character.yml", f"Failed to write: {e}")

    def _add_sprite_creator_poses(self, yml_path: Path, pose_letters: list) -> None:
        """Add pose letters to sprite_creator_poses list in character.yml.

        This tracks which poses were created by Sprite Creator, allowing
        expressions to be added to them later (unlike standard ST poses).
        """
        try:
            data = {}
            if yml_path.exists():
                with yml_path.open("r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}

            # Get existing list or create new one
            existing_poses = data.get('sprite_creator_poses', [])
            if not isinstance(existing_poses, list):
                existing_poses = []

            # Add new poses that aren't already in the list
            for letter in pose_letters:
                if letter not in existing_poses:
                    existing_poses.append(letter)

            data['sprite_creator_poses'] = sorted(existing_poses)

            with yml_path.open("w", encoding="utf-8") as f:
                yaml.dump(data, f, sort_keys=False, allow_unicode=True)
            log_info(f"Added poses to sprite_creator_poses: {pose_letters}")
        except Exception as e:
            log_error("Add sprite_creator poses", str(e))

    def validate(self) -> bool:
        """Always valid - just a summary screen."""
        return True
