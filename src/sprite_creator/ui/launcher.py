"""
Main Launcher Window for AI Sprite Creator.

Provides a graphical launcher with three tool options:
1. Character Sprite Creator (primary) - Full AI-powered sprite generation pipeline
2. Expression Sheet Generator - Generate sheets from existing character folders
3. Sprite Tester - Preview sprites in Ren'Py environment
"""

import shutil
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox
from pathlib import Path
from typing import Optional, Callable

from ..config import (
    APP_NAME,
    APP_VERSION,
    BG_COLOR,
    BG_SECONDARY,
    CARD_BG,
    CARD_BG_HOVER,
    TEXT_COLOR,
    TEXT_SECONDARY,
    ACCENT_COLOR,
    TITLE_FONT,
    SECTION_FONT,
    BODY_FONT,
    SMALL_FONT,
    CARD_PADDING,
    BACKUPS_BASE_DIR,
)
from .tk_common import (
    apply_dark_theme,
    apply_window_size,
    create_primary_button,
    create_secondary_button,
    create_help_button,
)
from .api_setup import show_api_setup, get_existing_api_key
from .welcome import show_welcome


# Google AI Studio usage dashboard URL
AI_STUDIO_USAGE_URL = "https://aistudio.google.com/usage"


# Help text for the launcher
LAUNCHER_HELP_TEXT = """Welcome to AI Sprite Creator!

Choose one of the tools:

Character Sprite Creator (Recommended)
The full character creation wizard. Start from a reference image, text
description, or fuse two characters together. Includes:
- AI-powered sprite generation with multiple outfits and expressions
- Fusion mode: merge two characters into one
- Automatic background removal and manual touch-up tools
- Scale comparison with reference sprites
- Expression sheet generation

Add to Character
Add new content to an existing character folder:
- Select a base sprite, then normalize it to match AI output resolution
- Add NEW outfits (becomes new pose letters: c, d, e...)
- Add NEW expressions to existing outfits
- REPLACE existing expressions that came out poorly (orange chips)
- Automatically matches scale to existing character
- Preserves all existing settings (voice, name, eye line, etc.)
- Full-size backup images are preferred for best quality

Expression Sheet Generator
Create expression reference sheets from existing character folders.
Use this if you already have characters and want visual reference sheets.

Sprite Tester
Preview character sprites in a simulated Ren'Py environment. Tests outfit
switching, expressions, and the character loading system.

Footer Buttons:
- API Settings: Configure your Google Gemini API key
- View API Usage: Opens Google AI Studio usage dashboard
- View README: Re-read the welcome guide and documentation
- Clear Backups: Delete full-size backup images to free disk space
  (reduces quality when adding to existing characters)

Note: You'll need a Google Cloud API key (not the basic AI Studio free
tier). New Google Cloud accounts get $300 in free credits."""


class ToolCard(tk.Frame):
    """
    A large clickable card for tool selection.
    """

    def __init__(
        self,
        parent: tk.Widget,
        title: str,
        description: str,
        icon_text: str = "",
        primary: bool = False,
        on_click: Optional[Callable] = None,
    ):
        # Primary cards get accent border
        highlight_color = ACCENT_COLOR if primary else CARD_BG
        super().__init__(parent, bg=CARD_BG, highlightbackground=highlight_color,
                         highlightthickness=2 if primary else 1)

        self._on_click = on_click
        self._primary = primary
        self._base_bg = CARD_BG

        # Padding frame
        inner = tk.Frame(self, bg=CARD_BG, padx=16, pady=10)
        inner.pack(fill="both", expand=True)

        # Icon/emoji area (optional)
        if icon_text:
            icon_label = tk.Label(
                inner,
                text=icon_text,
                bg=CARD_BG,
                fg=TEXT_COLOR,
                font=(SECTION_FONT[0], 22),
            )
            icon_label.pack(pady=(0, 4))
            icon_label.bind("<Button-1>", self._handle_click)
            icon_label.bind("<Enter>", self._on_enter)
            icon_label.bind("<Leave>", self._on_leave)

        # Title
        title_label = tk.Label(
            inner,
            text=title,
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=SECTION_FONT,
        )
        title_label.pack(pady=(0, 6))

        # Description
        desc_label = tk.Label(
            inner,
            text=description,
            bg=CARD_BG,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
            wraplength=220,
            justify="center",
        )
        desc_label.pack()

        # Primary badge
        if primary:
            badge = tk.Label(
                inner,
                text="Recommended",
                bg=ACCENT_COLOR,
                fg=TEXT_COLOR,
                font=(SMALL_FONT[0], 9),
                padx=8,
                pady=2,
            )
            badge.pack(pady=(10, 0))
            badge.bind("<Button-1>", self._handle_click)
            badge.bind("<Enter>", self._on_enter)
            badge.bind("<Leave>", self._on_leave)

        # Store references for hover effects
        self._inner = inner
        self._labels = [title_label, desc_label]
        if icon_text:
            self._labels.append(icon_label)

        # Bind click and hover
        self.bind("<Button-1>", self._handle_click)
        inner.bind("<Button-1>", self._handle_click)
        title_label.bind("<Button-1>", self._handle_click)
        desc_label.bind("<Button-1>", self._handle_click)

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        inner.bind("<Enter>", self._on_enter)
        inner.bind("<Leave>", self._on_leave)
        title_label.bind("<Enter>", self._on_enter)
        title_label.bind("<Leave>", self._on_leave)
        desc_label.bind("<Enter>", self._on_enter)
        desc_label.bind("<Leave>", self._on_leave)

        self.configure(cursor="hand2")

    def _handle_click(self, event=None):
        if self._on_click:
            self._on_click()

    def _on_enter(self, event=None):
        self._set_bg(CARD_BG_HOVER)

    def _on_leave(self, event=None):
        self._set_bg(self._base_bg)

    def _set_bg(self, color: str):
        self.configure(bg=color)
        self._inner.configure(bg=color)
        for label in self._labels:
            label.configure(bg=color)


class LauncherWindow:
    """
    Main launcher window for the AI Sprite Creator application.
    """

    def __init__(self, on_sprite_creator: Callable, on_expression_sheets: Callable,
                 on_sprite_tester: Callable, on_add_to_existing: Optional[Callable] = None):
        """
        Initialize the launcher window.

        Args:
            on_sprite_creator: Callback when Character Sprite Creator is selected
            on_expression_sheets: Callback when Expression Sheet Generator is selected
            on_sprite_tester: Callback when Sprite Tester is selected
            on_add_to_existing: Callback when Add to Character is selected
        """
        self._on_sprite_creator = on_sprite_creator
        self._on_expression_sheets = on_expression_sheets
        self._on_sprite_tester = on_sprite_tester
        self._on_add_to_existing = on_add_to_existing

        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Apply dark theme and sizing
        apply_dark_theme(self.root)
        apply_window_size(self.root, "large")

        self._build_ui()
        self._result: Optional[str] = None

    def _build_ui(self):
        """Build the launcher UI."""
        # Scrollable container for small screens
        self._scroll_canvas = tk.Canvas(self.root, bg=BG_COLOR, highlightthickness=0)
        self._scroll_canvas.pack(side="left", fill="both", expand=True)

        scrollbar = tk.Scrollbar(self.root, orient="vertical", command=self._scroll_canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self._scroll_canvas.configure(yscrollcommand=scrollbar.set)

        main_frame = tk.Frame(self._scroll_canvas, bg=BG_COLOR, padx=40, pady=20)
        self._scroll_canvas.create_window((0, 0), window=main_frame, anchor="nw")

        def _on_configure(event=None):
            self._scroll_canvas.configure(scrollregion=self._scroll_canvas.bbox("all"))
            # Match canvas width so content stays centered
            canvas_w = self._scroll_canvas.winfo_width()
            self._scroll_canvas.itemconfigure("all", width=canvas_w)
        main_frame.bind("<Configure>", _on_configure)

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            self._scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self._scroll_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Header with help button
        header_frame = tk.Frame(main_frame, bg=BG_COLOR)
        header_frame.pack(fill="x", pady=(0, 6))

        # Title area (left side)
        title_frame = tk.Frame(header_frame, bg=BG_COLOR)
        title_frame.pack(side="left", fill="x", expand=True)

        title_label = tk.Label(
            title_frame,
            text=APP_NAME,
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=TITLE_FONT,
        )
        title_label.pack(anchor="w")

        version_label = tk.Label(
            title_frame,
            text=f"Version {APP_VERSION}",
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        )
        version_label.pack(anchor="w")

        # Help button (right side)
        help_btn = create_help_button(header_frame, "About This Tool", LAUNCHER_HELP_TEXT)
        help_btn.pack(side="right", anchor="ne")

        # Subtitle
        subtitle_label = tk.Label(
            main_frame,
            text="AI-powered character sprite generation for visual novels",
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=BODY_FONT,
        )
        subtitle_label.pack(pady=(0, 16))

        # Tool cards container (2x2 grid)
        cards_frame = tk.Frame(main_frame, bg=BG_COLOR)
        cards_frame.pack(fill="both", expand=True)

        cards_frame.columnconfigure(0, weight=1)
        cards_frame.columnconfigure(1, weight=1)

        # Row 0: Sprite Creator (primary) + Add to Character
        card1 = ToolCard(
            cards_frame,
            title="Character Sprite\nCreator",
            description="Generate complete character sprites with AI. Includes expressions, outfits, and automatic processing.",
            icon_text="\u2728",  # Sparkles emoji
            primary=True,
            on_click=self._select_sprite_creator,
        )
        card1.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        card2 = ToolCard(
            cards_frame,
            title="Add to\nCharacter",
            description="Add new outfits or expressions to an existing character folder.",
            icon_text="\u2795",  # Plus sign emoji
            primary=False,
            on_click=self._select_add_to_existing,
        )
        card2.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")

        # Row 1: Expression Sheets + Sprite Tester
        card3 = ToolCard(
            cards_frame,
            title="Expression Sheet\nGenerator",
            description="Create expression reference sheets from existing character folders.",
            icon_text="\U0001F5BC",  # Frame emoji
            primary=False,
            on_click=self._select_expression_sheets,
        )
        card3.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

        card4 = ToolCard(
            cards_frame,
            title="Sprite\nTester",
            description="Preview character sprites in a Ren'Py environment with outfit and expression switching.",
            icon_text="\U0001F3AE",  # Game controller emoji
            primary=False,
            on_click=self._select_sprite_tester,
        )
        card4.grid(row=1, column=1, padx=10, pady=10, sticky="nsew")

        # Footer
        footer_frame = tk.Frame(main_frame, bg=BG_COLOR)
        footer_frame.pack(fill="x", pady=(16, 0))

        footer_text = tk.Label(
            footer_frame,
            text="Requires a Google Cloud API key (free $300 credits for new accounts)",
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        )
        footer_text.pack()

        # Button row for footer actions
        btn_row = tk.Frame(footer_frame, bg=BG_COLOR)
        btn_row.pack(pady=(10, 0))

        # API Settings button
        settings_btn = create_secondary_button(
            btn_row,
            "API Settings",
            self._open_api_settings,
            width=14,
        )
        settings_btn.pack(side="left", padx=(0, 8))

        # View Usage button
        usage_btn = create_secondary_button(
            btn_row,
            "View API Usage",
            self._open_usage_dashboard,
            width=14,
        )
        usage_btn.pack(side="left", padx=(0, 8))

        # View README button
        readme_btn = create_secondary_button(
            btn_row,
            "View README",
            self._open_readme,
            width=14,
        )
        readme_btn.pack(side="left", padx=(0, 8))

        # Clear Backups button
        clear_btn = create_secondary_button(
            btn_row,
            "Clear Backups",
            self._clear_backups,
            width=14,
        )
        clear_btn.pack(side="left")

    def _unbind_scroll(self):
        """Unbind scroll events before closing."""
        try:
            self._scroll_canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass

    def _select_sprite_creator(self):
        """Handle Character Sprite Creator selection."""
        self._result = "sprite_creator"
        self._unbind_scroll()
        self.root.quit()

    def _select_expression_sheets(self):
        """Handle Expression Sheet Generator selection."""
        self._result = "expression_sheets"
        self._unbind_scroll()
        self.root.quit()

    def _select_sprite_tester(self):
        """Handle Sprite Tester selection."""
        self._result = "sprite_tester"
        self._unbind_scroll()
        self.root.quit()

    def _select_add_to_existing(self):
        """Handle Add to Character selection."""
        self._result = "add_to_existing"
        self._unbind_scroll()
        self.root.quit()

    def _open_api_settings(self):
        """Open the API settings dialog to view/change the Gemini API key."""
        existing_key = get_existing_api_key() or ""
        # Show the API setup dialog as modal (passes parent so it works properly)
        show_api_setup(existing_key, parent=self.root)

    def _open_usage_dashboard(self):
        """Open the Google AI Studio usage dashboard in the default browser."""
        webbrowser.open(AI_STUDIO_USAGE_URL)

    def _open_readme(self):
        """Open the welcome/README window."""
        show_welcome(parent=self.root)

    def _clear_backups(self):
        """Clear all saved full-size character backups."""
        if not BACKUPS_BASE_DIR.exists() or not any(BACKUPS_BASE_DIR.iterdir()):
            messagebox.showinfo(
                "No Backups",
                "No backup files found. Nothing to clear.",
                parent=self.root,
            )
            return

        # Calculate current size
        total_size = sum(
            f.stat().st_size for f in BACKUPS_BASE_DIR.rglob("*") if f.is_file()
        )
        size_mb = total_size / (1024 * 1024)

        confirm = messagebox.askyesno(
            "Clear Backups",
            f"WARNING: This will delete all saved full-size character backups "
            f"({size_mb:.1f} MB).\n\n"
            f"If you add new content to characters created by this app, the results "
            f"will be of slightly lower quality without these backups.\n\n"
            f"The app will still work - it will use existing character images instead, "
            f"but the best quality comes from having these full-size backups.\n\n"
            f"This cannot be undone. Continue?",
            parent=self.root,
        )

        if confirm:
            try:
                shutil.rmtree(BACKUPS_BASE_DIR)
                BACKUPS_BASE_DIR.mkdir(parents=True, exist_ok=True)
                messagebox.showinfo(
                    "Backups Cleared",
                    f"Freed {size_mb:.1f} MB of backup data.",
                    parent=self.root,
                )
            except Exception as e:
                messagebox.showerror(
                    "Error",
                    f"Failed to clear backups:\n{e}",
                    parent=self.root,
                )

    def _on_close(self):
        """Handle window close."""
        self._result = None
        self._unbind_scroll()
        self.root.quit()

    def run(self) -> Optional[str]:
        """
        Run the launcher and return the selected tool.

        Returns:
            "sprite_creator", "expression_sheets", "sprite_tester", "add_to_existing", or None if closed
        """
        self.root.mainloop()
        result = self._result
        self.root.destroy()
        return result


def select_character_folder(title: str = "Select Character Folder") -> Optional[Path]:
    """
    Show a folder selection dialog for choosing a character folder.

    Args:
        title: Dialog title

    Returns:
        Path to selected folder, or None if cancelled
    """
    root = tk.Tk()
    root.withdraw()

    folder = filedialog.askdirectory(title=title)

    root.destroy()

    if folder:
        return Path(folder)
    return None


def run_launcher() -> Optional[str]:
    """
    Create and run the launcher window.

    Returns:
        Selected tool name or None if closed
    """
    # Placeholder callbacks - the actual implementation will wire these up
    def on_sprite_creator():
        pass

    def on_expression_sheets():
        pass

    def on_sprite_tester():
        pass

    launcher = LauncherWindow(on_sprite_creator, on_expression_sheets, on_sprite_tester)
    return launcher.run()


# For testing
if __name__ == "__main__":
    result = run_launcher()
    print(f"Selected: {result}")
