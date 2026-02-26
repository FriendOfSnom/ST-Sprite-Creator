"""
Welcome/README Screen for ST Sprite Creator.

Shows a welcome screen on first launch with app overview and instructions.
Can also be opened from the main launcher via "View README" button.
"""

import json
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from typing import Optional

from ..config import (
    CONFIG_PATH,
    BG_COLOR,
    TEXT_COLOR,
    TEXT_SECONDARY,
    TITLE_FONT,
    SECTION_FONT,
    BODY_FONT,
    SMALL_FONT,
)
from .tk_common import (
    apply_dark_theme,
    apply_window_size,
    create_primary_button,
)
from .disclaimer import load_config, save_config


# README content displayed in the welcome window
WELCOME_TEXT = """ST Sprite Creator

AI-powered character sprite generator for Student Transfer, using Google Gemini.
Create complete characters with multiple outfits and expressions in minutes.


LAUNCHER MODES

  Character Sprite Creator (Recommended)
  The full character creation wizard. Start from a reference image, text
  description, or fuse two characters together. Generates multiple outfits
  and expressions with automatic background removal, cropping, and scaling.

  Add to Character
  Add new outfits or expressions to an existing character folder. Selects
  a base sprite from the character, normalizes it to match AI output
  resolution, then generates new content that matches the existing style.
  New outfits become new pose letters (c, d, e...).

  Expression Sheet Generator
  Create expression reference sheet images from existing character folders.
  Useful if you already have characters and want visual reference sheets.

  Sprite Tester
  Preview character sprites in a simulated Ren'Py environment. Tests outfit
  switching, expressions, and the character loading system.


WIZARD STEPS (Character Sprite Creator)

  1. Source Selection - Image upload, text prompt, or character fusion
  2. Character Setup - Name, voice, archetype, crop/normalize the base
  3. Generation Options - Select outfits and expressions to generate
  4. Review - Confirm selections before generation begins
  5. Outfit Review - Review outfits, adjust background removal
  6. Expression Review - Review expressions, touch up backgrounds
  7. Eye Line & Color - Set eye position and name color
  8. Scale - Compare with reference sprites for in-game sizing
  9. Complete - View summary and open character folder


OUTPUT STRUCTURE

  character_name/
    character.yml           Metadata (voice, scale, eye line, colors)
    base.png                Original base image for reference
    a/                      Pose A (first outfit)
      outfits/0.png         Outfit image (body without expression)
      faces/face/
        0.png               Neutral expression (full character)
        1.png               Happy
        2.png               Sad
        ...                 Additional expressions
    b/                      Pose B (second outfit)
      ...
    expression_sheets/      Generated sprite sheets for reference


API SETUP

  This tool requires a Google Cloud API key with Gemini access.
  New Google Cloud accounts get $300 in free credits.

  To set up your API key:
  1. Go to Google AI Studio (aistudio.google.com)
  2. Create a project and enable the Gemini API
  3. Generate an API key
  4. Enter it in the API Settings dialog on the launcher

  Your key is stored locally in ~/.st_gemini_config.json


BACKUP SYSTEM

  Full-size character images are automatically backed up before scaling.
  These backups live in ~/.sprite_creator/backups/ and are used when
  adding new content to existing characters for best quality results.
  Use "Clear Backups" on the launcher to free disk space if needed.


TIPS

  - Every wizard step has a ? help button with detailed instructions
  - Use ST Style toggle to match Student Transfer art style (or disable
    for any art style you want)
  - If Gemini's safety filters block a generation, the wizard skips it
    and continues with successful items
  - You can regenerate individual outfits and expressions without
    starting over
  - Characters are compatible with Student Transfer's character system
    and Ren'Py projects that use the same format
"""


class WelcomeWindow:
    """
    Welcome/README window shown on first launch or from launcher button.
    """

    def __init__(self, parent: Optional[tk.Tk] = None):
        """
        Initialize the welcome window.

        Args:
            parent: Optional parent window. If provided, opens as a modal
                    dialog. If None, creates its own root window.
        """
        self._is_modal = parent is not None

        if self._is_modal:
            self.root = tk.Toplevel(parent)
            self.root.transient(parent)
            self.root.grab_set()
        else:
            self.root = tk.Tk()

        self.root.title("Welcome - ST Sprite Creator")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        apply_dark_theme(self.root)
        apply_window_size(self.root, "standard")

        self._build_ui()

    def _build_ui(self):
        """Build the welcome UI."""
        main_frame = tk.Frame(self.root, bg=BG_COLOR, padx=30, pady=24)
        main_frame.pack(fill="both", expand=True)

        # Title
        tk.Label(
            main_frame,
            text="Welcome to ST Sprite Creator",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=TITLE_FONT,
        ).pack(pady=(0, 4))

        tk.Label(
            main_frame,
            text="Read through the guide below to get started",
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        ).pack(pady=(0, 16))

        # Scrollable text area
        text_frame = tk.Frame(main_frame, bg=BG_COLOR)
        text_frame.pack(fill="both", expand=True, pady=(0, 16))

        text_widget = tk.Text(
            text_frame,
            wrap="word",
            bg="#1E1E1E",
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#444444",
            padx=16,
            pady=16,
        )
        text_widget.insert("1.0", WELCOME_TEXT)
        text_widget.configure(state="disabled")

        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)

        text_widget.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Close button
        close_btn = create_primary_button(
            main_frame,
            "Close",
            self._on_close,
            width=12,
        )
        close_btn.pack()

    def _on_close(self):
        """Handle close button or window close."""
        if self._is_modal:
            self.root.grab_release()
            self.root.destroy()
        else:
            self.root.quit()

    def run(self):
        """Run the welcome window (blocking, for standalone use)."""
        self.root.mainloop()
        if not self._is_modal:
            self.root.destroy()


def has_seen_welcome() -> bool:
    """Check if the user has already seen the welcome screen."""
    config = load_config()
    return config.get("readme_shown", False)


def record_welcome_shown() -> None:
    """Record that the user has seen the welcome screen."""
    config = load_config()
    config["readme_shown"] = True
    save_config(config)


def show_welcome_if_needed() -> None:
    """Show the welcome screen on first launch (after disclaimer)."""
    if has_seen_welcome():
        return

    window = WelcomeWindow()
    window.run()
    record_welcome_shown()


def show_welcome(parent: Optional[tk.Tk] = None) -> None:
    """Show the welcome screen (always, for launcher button)."""
    window = WelcomeWindow(parent=parent)
    if parent:
        # Modal - just wait for it to close
        parent.wait_window(window.root)
    else:
        window.run()
