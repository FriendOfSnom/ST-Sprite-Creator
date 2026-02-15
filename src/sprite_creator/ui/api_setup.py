"""
API Key Setup Screen for AI Sprite Creator.

Provides a GUI dialog for entering and validating Gemini API keys,
replacing the CLI-based interactive setup.
"""

import json
import queue
import threading
import tkinter as tk
from tkinter import ttk
import webbrowser
from typing import Optional

from ..config import (
    CONFIG_PATH,
    GEMINI_API_URL,
    BG_COLOR,
    CARD_BG,
    TEXT_COLOR,
    TEXT_SECONDARY,
    ACCENT_COLOR,
    SUCCESS_COLOR,
    DANGER_COLOR,
    WARNING_TEXT,
    TITLE_FONT,
    SECTION_FONT,
    BODY_FONT,
    SMALL_FONT,
)
from .tk_common import (
    apply_dark_theme,
    apply_window_size,
    create_primary_button,
    create_secondary_button,
    create_help_button,
)


API_SETUP_HELP_TEXT = """Getting Your Gemini API Key

IMPORTANT: You need a Google Cloud account with credits!
The basic free tier from AI Studio does NOT have enough quota for sprite generation. You need to set up Google Cloud to get $300 in free credits.

Step-by-Step Setup:

1. Go to console.cloud.google.com
2. Sign in or create a Google account
3. New accounts automatically get $300 in free trial credits
4. Create a new project (or use default)
5. Search for "Generative Language API" and enable it
6. Go to "APIs & Services" > "Credentials"
7. Click "Create Credentials" > "API Key"
8. Copy the key and paste it here

Why Google Cloud Instead of AI Studio?
- AI Studio's free tier has very strict rate limits
- Sprite generation requires many API calls
- The $300 Cloud credits provide much higher limits
- One character with multiple outfits = 50+ API calls

TROUBLESHOOTING

"API key changed but still getting errors"
If you have a GEMINI_API_KEY environment variable set, it takes precedence over the saved config. Check your system/user environment variables and remove it, then restart the app.

"Invalid API key" error:
The key may have been deleted or restricted. Generate a new one from Google Cloud Console.

"Quota exceeded" or "429" errors:
This almost always means you're using an AI Studio free-tier key instead of a Google Cloud key. The free tier has zero or very low quota for image generation. Set up Google Cloud billing as described above to get $300 in free credits.

"Safety filter" errors:
The AI refused to generate certain content. Try different prompts or descriptions.

"403 Forbidden" error:
The API is not enabled for your project, or the key is restricted. Enable "Generative Language API" in Google Cloud Console.

API Key Security:
Your key is stored locally (~/.st_gemini_config.json) and only used to communicate with Google. Never shared.

When Credits Run Low:
Google Cloud's $300 free trial lasts about 90 days. After it runs out, you can create a new Google account to get fresh credits. The same API key setup process applies."""


class APISetupWindow:
    """
    GUI dialog for entering and validating Gemini API keys.
    """

    def __init__(self, existing_key: str = "", parent: Optional[tk.Tk] = None):
        """
        Initialize the API setup window.

        Args:
            existing_key: Pre-existing API key to display (masked)
            parent: Optional parent window. If provided, opens as Toplevel dialog.
        """
        self._is_toplevel = parent is not None
        self._parent = parent

        if self._is_toplevel:
            self.root = tk.Toplevel(parent)
            self.root.transient(parent)  # Stay on top of parent
            # Note: grab_set() is called later after window is fully configured
        else:
            self.root = tk.Tk()

        self.root.title("API Key Setup")
        self.root.protocol("WM_DELETE_WINDOW", self._on_cancel)

        apply_dark_theme(self.root)
        apply_window_size(self.root, "compact")

        self._existing_key = existing_key
        self._result_key: Optional[str] = None
        self._is_validating = False

        # Thread-safe callback queue (same pattern as FullWizard)
        self._callback_queue: queue.Queue = queue.Queue()

        self._build_ui()
        self._start_callback_processor()

        # Center on parent if toplevel and set up modal behavior
        if self._is_toplevel and parent:
            self.root.update_idletasks()
            # Center the dialog on the parent window
            px = parent.winfo_x()
            py = parent.winfo_y()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            w = self.root.winfo_width()
            h = self.root.winfo_height()
            x = px + (pw - w) // 2
            y = py + (ph - h) // 2
            self.root.geometry(f"+{x}+{y}")

            # Lift window above parent
            self.root.lift()

            # Defer modal setup slightly to ensure window is fully mapped
            # This fixes event processing issues on some systems
            def setup_modal():
                try:
                    if self.root.winfo_exists():
                        self.root.focus_force()
                        self.root.grab_set()
                        self._key_entry.focus_set()
                except tk.TclError:
                    pass  # Window was closed

            self.root.after(50, setup_modal)

    def _start_callback_processor(self):
        """Start processing the thread-safe callback queue."""
        try:
            while True:
                callback = self._callback_queue.get_nowait()
                callback()
        except queue.Empty:
            pass
        # Only continue polling if window still exists
        try:
            if self.root.winfo_exists():
                self.root.after(100, self._start_callback_processor)
        except tk.TclError:
            pass

    def _schedule_callback(self, callback):
        """Schedule a callback on the main thread (thread-safe)."""
        self._callback_queue.put(callback)

    def _build_ui(self):
        """Build the API setup UI."""
        # Main container
        main_frame = tk.Frame(self.root, bg=BG_COLOR, padx=30, pady=24)
        main_frame.pack(fill="both", expand=True)

        # Header with help button
        header_frame = tk.Frame(main_frame, bg=BG_COLOR)
        header_frame.pack(fill="x", pady=(0, 16))

        title_label = tk.Label(
            header_frame,
            text="Gemini API Key",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=TITLE_FONT,
        )
        title_label.pack(side="left")

        help_btn = create_help_button(header_frame, "API Key Help", API_SETUP_HELP_TEXT)
        help_btn.pack(side="right")

        # Check for environment variable override
        import os
        env_key = os.environ.get("GEMINI_API_KEY")
        if env_key:
            # Show warning that env var takes precedence
            warning_frame = tk.Frame(main_frame, bg=CARD_BG, padx=12, pady=8)
            warning_frame.pack(fill="x", pady=(0, 12))

            tk.Label(
                warning_frame,
                text="⚠️ Environment Variable Detected",
                bg=CARD_BG,
                fg=WARNING_TEXT,
                font=SECTION_FONT,
            ).pack(anchor="w")

            tk.Label(
                warning_frame,
                text="The GEMINI_API_KEY environment variable is set.\n"
                     "This takes precedence over any key saved here.\n"
                     "To use a different key, unset the environment variable first.",
                bg=CARD_BG,
                fg=TEXT_COLOR,
                font=SMALL_FONT,
                justify="left",
                wraplength=380,
            ).pack(anchor="w", pady=(4, 0))

        # Description
        desc_text = (
            "You need a Google Cloud API key (not AI Studio free tier).\n"
            "New Google Cloud accounts get $300 in free credits.\n"
            "Click the ? button for setup instructions."
        )
        desc_label = tk.Label(
            main_frame,
            text=desc_text,
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=BODY_FONT,
            justify="left",
            wraplength=400,
        )
        desc_label.pack(anchor="w", pady=(0, 20))

        # Open browser button
        browser_btn = create_secondary_button(
            main_frame,
            "Open Google AI Studio",
            self._open_api_page,
            width=22,
        )
        browser_btn.pack(pady=(0, 20))

        # API key input section
        input_frame = tk.Frame(main_frame, bg=BG_COLOR)
        input_frame.pack(fill="x", pady=(0, 8))

        key_label = tk.Label(
            input_frame,
            text="API Key:",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=BODY_FONT,
        )
        key_label.pack(anchor="w", pady=(0, 6))

        # Entry with show/hide toggle
        entry_frame = tk.Frame(input_frame, bg=BG_COLOR)
        entry_frame.pack(fill="x")

        self._key_var = tk.StringVar()
        self._key_entry = tk.Entry(
            entry_frame,
            textvariable=self._key_var,
            font=BODY_FONT,
            width=45,
            show="*",
            bg="#1E1E1E",
            fg=TEXT_COLOR,
            insertbackground=TEXT_COLOR,
            highlightthickness=1,
            highlightbackground="#444444",
            highlightcolor=ACCENT_COLOR,
        )
        self._key_entry.pack(side="left", fill="x", expand=True)

        # Show/hide password toggle button
        self._key_visible = False
        self._show_btn = tk.Button(
            entry_frame,
            text="Show",
            command=self._toggle_key_visibility,
            bg=CARD_BG,
            fg=TEXT_COLOR,
            activebackground="#3D3D3D",
            activeforeground=TEXT_COLOR,
            relief="flat",
            padx=8,
            pady=2,
            cursor="hand2",
        )
        self._show_btn.pack(side="left", padx=(8, 0))

        # Pre-fill with masked existing key indicator
        if self._existing_key:
            self._key_var.set(self._existing_key)

        # Status label (for validation feedback)
        self._status_var = tk.StringVar()
        self._status_label = tk.Label(
            main_frame,
            textvariable=self._status_var,
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        )
        self._status_label.pack(anchor="w", pady=(0, 20))

        # Tip text
        tip_text = (
            "Tip: When your $300 credits run low, create a new Google\n"
            "account to get fresh credits. See ? for full instructions."
        )
        tip_label = tk.Label(
            main_frame,
            text=tip_text,
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
            justify="left",
        )
        tip_label.pack(anchor="w", pady=(0, 20))

        # Buttons
        button_frame = tk.Frame(main_frame, bg=BG_COLOR)
        button_frame.pack(fill="x")

        self._save_btn = create_primary_button(
            button_frame,
            "Verify & Save",
            self._on_verify_and_save,
            width=15,
        )
        self._save_btn.pack(side="right", padx=(10, 0))

        cancel_btn = create_secondary_button(
            button_frame,
            "Cancel",
            self._on_cancel,
            width=10,
        )
        cancel_btn.pack(side="right")

        # Bind Enter key
        self._key_entry.bind("<Return>", lambda e: self._on_verify_and_save())

        # Focus will be set after window is fully configured (in __init__ for Toplevel,
        # or immediately for standalone Tk)
        if not self._is_toplevel:
            self._key_entry.focus_set()

    def _toggle_key_visibility(self):
        """Toggle API key visibility."""
        self._key_visible = not self._key_visible
        if self._key_visible:
            self._key_entry.configure(show="")
            self._show_btn.configure(text="Hide")
        else:
            self._key_entry.configure(show="*")
            self._show_btn.configure(text="Show")

    def _open_api_page(self):
        """Open the Google AI Studio API key page in browser."""
        url = "https://aistudio.google.com/app/apikey"
        try:
            webbrowser.open(url)
            self._set_status("Browser opened. Copy your API key and paste it above.", TEXT_SECONDARY)
        except Exception as e:
            self._set_status(f"Could not open browser: {e}", DANGER_COLOR)

    def _set_status(self, message: str, color: str = TEXT_SECONDARY):
        """Set the status message."""
        self._status_var.set(message)
        self._status_label.configure(fg=color)

    def _validate_api_key(self, api_key: str) -> tuple[bool, str]:
        """
        Validate an API key by making a simple API call.

        Returns:
            (success, message) tuple
        """
        import requests

        if not api_key or len(api_key) < 10:
            return False, "API key appears too short"

        # Try a simple request to check if the key is valid
        test_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"

        try:
            response = requests.get(test_url, timeout=10)

            if response.status_code == 200:
                return True, "API key is valid!"
            elif response.status_code == 400:
                return False, "Invalid API key format"
            elif response.status_code == 403:
                return False, "API key is invalid or has been revoked"
            else:
                return False, f"Validation failed: HTTP {response.status_code}"

        except requests.exceptions.Timeout:
            return False, "Connection timed out. Check your internet connection."
        except requests.exceptions.ConnectionError:
            return False, "Connection failed. Check your internet connection."
        except Exception as e:
            return False, f"Validation error: {str(e)}"

    def _on_verify_and_save(self):
        """Handle verify and save button click."""
        if self._is_validating:
            return

        api_key = self._key_var.get().strip()

        if not api_key:
            self._set_status("Please enter an API key", DANGER_COLOR)
            return

        # Show validating state
        self._is_validating = True
        self._set_status("Validating API key...", TEXT_SECONDARY)
        self._save_btn.configure(state="disabled")

        # Run validation in background thread to keep UI responsive
        def validate_in_thread():
            success, message = self._validate_api_key(api_key)
            # Schedule callback on main thread (thread-safe)
            self._schedule_callback(lambda: self._on_validation_complete(api_key, success, message))

        thread = threading.Thread(target=validate_in_thread, daemon=True)
        thread.start()

    def _on_validation_complete(self, api_key: str, success: bool, message: str):
        """Handle validation completion (called on main thread)."""
        # Check if window still exists (user might have closed it)
        try:
            if not self.root.winfo_exists():
                return
        except tk.TclError:
            return

        self._is_validating = False
        self._save_btn.configure(state="normal")

        if success:
            self._set_status(message, SUCCESS_COLOR)
            self._result_key = api_key
            # Save to config
            self._save_api_key(api_key)
            # Close after short delay to show success message
            self.root.after(800, self._close_window)
        else:
            self._set_status(message, DANGER_COLOR)

    def _save_api_key(self, api_key: str):
        """Save API key to config file."""
        config = {}
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        config["api_key"] = api_key

        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

    def _on_cancel(self):
        """Handle cancel button or window close."""
        self._result_key = None
        self._close_window()

    def _close_window(self):
        """Close the window appropriately based on window type."""
        if self._is_toplevel:
            self.root.grab_release()
            self.root.destroy()
        else:
            self.root.quit()

    def run(self) -> Optional[str]:
        """
        Run the API setup dialog.

        Returns:
            The validated API key, or None if cancelled
        """
        if self._is_toplevel:
            # For toplevel, wait for window to close
            self.root.wait_window(self.root)
        else:
            # For standalone Tk, use mainloop
            self.root.mainloop()
            self.root.destroy()

        return self._result_key


def get_existing_api_key() -> Optional[str]:
    """
    Get existing API key from environment or config.

    Returns:
        API key if found, None otherwise
    """
    import os

    # Check environment variable first
    env_key = os.environ.get("GEMINI_API_KEY")
    if env_key:
        return env_key

    # Check config file
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)
                return config.get("api_key")
        except (json.JSONDecodeError, IOError):
            pass

    return None


def show_api_setup(existing_key: str = "", parent: Optional[tk.Tk] = None) -> Optional[str]:
    """
    Show the API setup dialog.

    Args:
        existing_key: Pre-existing API key to display
        parent: Optional parent window. If provided, opens as modal dialog.

    Returns:
        The validated API key, or None if cancelled
    """
    window = APISetupWindow(existing_key, parent=parent)
    return window.run()


def ensure_api_key() -> Optional[str]:
    """
    Ensure we have a valid API key, showing setup dialog if needed.

    Returns:
        Valid API key, or None if user cancelled setup
    """
    existing = get_existing_api_key()

    if existing:
        return existing

    # Show setup dialog
    return show_api_setup()


# For testing
if __name__ == "__main__":
    existing = get_existing_api_key()
    result = show_api_setup(existing or "")
    print(f"Result: {result}")
