"""
Gemini Workshop - Standalone image editing/generation window.

A simple Gemini-powered tool for img2img editing or txt2img generation
with optional Student Transfer style references. Not part of the main
character creation pipeline.
"""

import base64
import random
import tempfile
import threading
import tkinter as tk
from io import BytesIO
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional, List

from PIL import Image, ImageTk

from ..config import (
    BG_COLOR,
    BG_SECONDARY,
    CARD_BG,
    TEXT_COLOR,
    TEXT_SECONDARY,
    SECTION_FONT,
    BODY_FONT,
    SMALL_FONT,
    REF_SPRITES_DIR,
    GENDER_ARCHETYPES,
)
from ..api.gemini_client import (
    call_gemini_image_edit,
    call_gemini_text_or_refs,
    strip_background_ai,
    _call_gemini_with_parts,
    load_image_as_base64,
)
from ..logging_utils import log_info, log_exception
from .tk_common import (
    apply_dark_theme,
    apply_window_size,
    create_primary_button,
    create_secondary_button,
)
from .review_windows import click_to_remove_background


# Max thumbnail size for the preview panels
_PREVIEW_MAX = 420


def _get_all_style_refs(max_images: int = 8) -> List[Path]:
    """Grab up to *max_images* random reference sprites from all archetype folders."""
    all_paths: List[Path] = []
    if not REF_SPRITES_DIR.is_dir():
        return all_paths
    for child in REF_SPRITES_DIR.iterdir():
        if child.is_dir() and child.name not in ("backgrounds", "scale_references"):
            for p in child.iterdir():
                if p.suffix.lower() in (".png", ".webp", ".jpg", ".jpeg"):
                    all_paths.append(p)
    if len(all_paths) <= max_images:
        return all_paths
    return random.sample(all_paths, max_images)


def _get_archetype_refs(archetype_label: str) -> List[Path]:
    """Get reference images for a specific archetype."""
    from ..processing.image_utils import get_reference_images_for_archetype
    return get_reference_images_for_archetype(archetype_label)


def _pil_to_tk(image: Image.Image, max_size: int = _PREVIEW_MAX) -> ImageTk.PhotoImage:
    """Resize a PIL image to fit within max_size and convert to PhotoImage."""
    img = image.copy()
    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(img)


class GeminiWorkshop:
    """Standalone Gemini Workshop window."""

    def __init__(self, api_key: str):
        self._api_key = api_key

        # State
        self._input_image: Optional[Image.Image] = None  # User-loaded input
        self._raw_result: Optional[Image.Image] = None    # Raw Gemini output (never modified)
        self._current_result: Optional[Image.Image] = None  # Displayed result (may have BG removal)
        self._busy = False

        # Tk image references (prevent GC)
        self._input_tk: Optional[ImageTk.PhotoImage] = None
        self._result_tk: Optional[ImageTk.PhotoImage] = None

        # History gallery: list of PIL images, and their tk thumbnails (prevent GC)
        self._history_images: List[Image.Image] = []
        self._history_tks: List[ImageTk.PhotoImage] = []

        # Build window
        self.root = tk.Tk()
        self.root.title("Gemini Workshop")
        apply_dark_theme(self.root)
        apply_window_size(self.root, "large")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()

    # ── UI construction ──────────────────────────────────────────────────

    def _build_ui(self):
        # Scrollable container (same pattern as launcher)
        scroll_outer = tk.Frame(self.root, bg=BG_COLOR)
        scroll_outer.pack(fill="both", expand=True)

        self._scroll_canvas = tk.Canvas(scroll_outer, bg=BG_COLOR, highlightthickness=0)
        self._scroll_canvas.pack(fill="both", expand=True)

        self._v_scrollbar = tk.Scrollbar(
            scroll_outer, orient="vertical",
            command=self._scroll_canvas.yview, width=10,
        )
        self._h_scrollbar = tk.Scrollbar(
            scroll_outer, orient="horizontal",
            command=self._scroll_canvas.xview, width=10,
        )
        self._scroll_canvas.configure(
            xscrollcommand=self._h_scrollbar.set,
            yscrollcommand=self._v_scrollbar.set,
        )

        main = tk.Frame(self._scroll_canvas, bg=BG_COLOR, padx=24, pady=16)
        self._canvas_window = self._scroll_canvas.create_window((0, 0), window=main, anchor="nw")

        def _on_configure(event=None):
            self._scroll_canvas.configure(scrollregion=self._scroll_canvas.bbox("all"))
            canvas_w = self._scroll_canvas.winfo_width()
            content_w = main.winfo_reqwidth()
            self._scroll_canvas.itemconfigure(self._canvas_window, width=max(canvas_w, content_w))
            self._update_scrollbar()

        main.bind("<Configure>", _on_configure)
        self._scroll_canvas.bind("<Configure>", lambda e: _on_configure())
        self._main_frame = main

        # Title
        tk.Label(
            main, text="Gemini Workshop", bg=BG_COLOR, fg=TEXT_COLOR, font=SECTION_FONT,
        ).pack(anchor="w")

        # Tip
        tk.Label(
            main,
            text=(
                "Load an image for img2img editing, or leave empty to generate from text. "
                "Style references help match the Student Transfer art style."
            ),
            bg=BG_COLOR, fg=TEXT_SECONDARY, font=SMALL_FONT,
            wraplength=800, justify="left",
        ).pack(anchor="w", pady=(2, 10))

        # ── Image panels ────────────────────────────────────────────────
        panels = tk.Frame(main, bg=BG_COLOR)
        panels.pack(fill="x")
        panels.columnconfigure(0, weight=1)
        panels.columnconfigure(1, weight=1)
        panels.rowconfigure(0, weight=0)

        # Left: Input
        left = tk.Frame(panels, bg=BG_SECONDARY, highlightbackground=CARD_BG, highlightthickness=1)
        left.grid(row=0, column=0, padx=(0, 6), sticky="new")

        self._input_label = tk.Label(
            left, text="No image loaded", bg=BG_SECONDARY, fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        )
        self._input_label.pack(padx=8, pady=8)
        # Set a minimum height so the empty panel isn't tiny
        self._input_label.configure(height=24)

        left_btns = tk.Frame(left, bg=BG_SECONDARY)
        left_btns.pack(fill="x", padx=4, pady=(0, 6))
        create_secondary_button(left_btns, "Browse...", self._browse_input, width=10).pack(side="left", padx=(0, 4))
        create_secondary_button(left_btns, "Clear", self._clear_input, width=8).pack(side="left", padx=(0, 4))
        self._save_input_btn = create_secondary_button(left_btns, "Save", self._save_input, width=8)
        self._save_input_btn.pack(side="left")

        # Right: Result
        right = tk.Frame(panels, bg=BG_SECONDARY, highlightbackground=CARD_BG, highlightthickness=1)
        right.grid(row=0, column=1, padx=(6, 0), sticky="new")

        self._result_label = tk.Label(
            right, text="No result yet", bg=BG_SECONDARY, fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        )
        self._result_label.pack(padx=8, pady=8)
        self._result_label.configure(height=24)

        right_btns = tk.Frame(right, bg=BG_SECONDARY)
        right_btns.pack(fill="x", padx=4, pady=(0, 6))
        self._auto_bg_btn = create_secondary_button(right_btns, "Auto BG", self._auto_bg_remove, width=8)
        self._auto_bg_btn.pack(side="left", padx=(0, 4))
        self._manual_btn = create_secondary_button(right_btns, "Manual", self._manual_bg_remove, width=8)
        self._manual_btn.pack(side="left", padx=(0, 4))
        self._restore_btn = create_secondary_button(right_btns, "Restore", self._restore_result, width=8)
        self._restore_btn.pack(side="left", padx=(0, 4))
        self._keep_btn = create_secondary_button(right_btns, "Keep", self._keep_result, width=8)
        self._keep_btn.pack(side="left", padx=(0, 4))
        self._save_btn = create_secondary_button(right_btns, "Save", self._save_result, width=8)
        self._save_btn.pack(side="left")

        # ── Style references ────────────────────────────────────────────
        style_row = tk.Frame(main, bg=BG_COLOR)
        style_row.pack(fill="x", pady=(10, 0))

        self._use_refs_var = tk.BooleanVar(value=False)
        self._refs_check = tk.Checkbutton(
            style_row, text="Use ST style references", variable=self._use_refs_var,
            bg=BG_COLOR, fg=TEXT_COLOR, selectcolor=CARD_BG,
            activebackground=BG_COLOR, activeforeground=TEXT_COLOR,
            font=BODY_FONT, command=self._on_refs_toggle,
        )
        self._refs_check.pack(side="left")

        # Archetype dropdown
        archetype_names = ["All"] + [label for label, _ in GENDER_ARCHETYPES]
        self._archetype_var = tk.StringVar(value="All")
        self._archetype_menu = tk.OptionMenu(style_row, self._archetype_var, *archetype_names)
        self._archetype_menu.configure(
            width=16, bg=CARD_BG, fg=TEXT_COLOR, font=SMALL_FONT,
            highlightthickness=0, activebackground=CARD_BG, activeforeground=TEXT_COLOR,
        )
        self._archetype_menu["menu"].configure(bg=CARD_BG, fg=TEXT_COLOR)
        self._archetype_menu.pack(side="left", padx=(8, 0))
        self._archetype_menu.configure(state="disabled")  # Disabled until checkbox is checked

        # ── Prompt ──────────────────────────────────────────────────────
        prompt_frame = tk.Frame(main, bg=BG_COLOR)
        prompt_frame.pack(fill="x", pady=(10, 0))

        tk.Label(
            prompt_frame, text="Prompt:", bg=BG_COLOR, fg=TEXT_COLOR, font=BODY_FONT,
        ).pack(anchor="w")

        self._prompt_text = tk.Text(
            prompt_frame, height=3, wrap="word",
            bg=CARD_BG, fg=TEXT_COLOR, font=BODY_FONT,
            insertbackground=TEXT_COLOR, relief="flat",
            padx=8, pady=6,
        )
        self._prompt_text.pack(fill="x", pady=(4, 0))

        # ── Generate button ─────────────────────────────────────────────
        gen_frame = tk.Frame(main, bg=BG_COLOR)
        gen_frame.pack(pady=(10, 0))

        self._generate_btn = create_primary_button(
            gen_frame, "Generate", self._on_generate, width=16, large=True,
        )
        self._generate_btn.pack()

        # ── Status label ────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="")
        self._status_label = tk.Label(
            main, textvariable=self._status_var, bg=BG_COLOR, fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        )
        self._status_label.pack(pady=(6, 0))

        # ── History gallery ───────────────────────────────────────────
        hist_header = tk.Frame(main, bg=BG_COLOR)
        hist_header.pack(fill="x", pady=(12, 0))
        tk.Label(
            hist_header, text="History", bg=BG_COLOR, fg=TEXT_COLOR, font=BODY_FONT,
        ).pack(side="left")
        self._clear_hist_btn = create_secondary_button(hist_header, "Clear", self._clear_history, width=6)
        self._clear_hist_btn.pack(side="left", padx=(8, 0))

        self._history_frame = tk.Frame(main, bg=BG_COLOR)
        self._history_frame.pack(fill="x", pady=(4, 0))

        self._history_placeholder = tk.Label(
            self._history_frame, text="Generated images will appear here. Click one to use it as input.",
            bg=BG_COLOR, fg=TEXT_SECONDARY, font=SMALL_FONT,
        )
        self._history_placeholder.pack(anchor="w")

        # Initial button state
        self._update_result_buttons()

    # ── Scrollbar management ─────────────────────────────────────────────

    def _update_scrollbar(self) -> None:
        """Show scrollbars only when content overflows."""
        try:
            canvas_w = self._scroll_canvas.winfo_width()
            canvas_h = self._scroll_canvas.winfo_height()
            content_w = self._main_frame.winfo_reqwidth()
            content_h = self._main_frame.winfo_reqheight()
        except tk.TclError:
            return
        if content_h > canvas_h + 2:
            self._v_scrollbar.place(relx=1.0, rely=0, relheight=1.0, anchor="ne")
        else:
            self._v_scrollbar.place_forget()
        if content_w > canvas_w + 2:
            self._h_scrollbar.place(relx=0, rely=1.0, relwidth=1.0, anchor="sw")
        else:
            self._h_scrollbar.place_forget()

    # ── Input management ─────────────────────────────────────────────────

    def _browse_input(self):
        if self._busy:
            return
        path = filedialog.askopenfilename(
            title="Select input image",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp *.bmp")],
            parent=self.root,
        )
        if not path:
            return
        try:
            img = Image.open(path).convert("RGBA")
            self._input_image = img
            self._input_tk = _pil_to_tk(img)
            self._input_label.configure(image=self._input_tk, text="", height=0)
            self._add_to_history(img)
            self._update_result_buttons()
            log_info(f"WORKSHOP: Loaded input image: {path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load image:\n{e}", parent=self.root)

    def _clear_input(self):
        if self._busy:
            return
        self._input_image = None
        self._input_tk = None
        self._input_label.configure(image="", text="No image loaded", height=24)
        self._update_result_buttons()

    # ── Style refs toggle ────────────────────────────────────────────────

    def _on_refs_toggle(self):
        if self._use_refs_var.get():
            self._archetype_menu.configure(state="normal")
        else:
            self._archetype_menu.configure(state="disabled")

    def _get_selected_refs(self) -> Optional[List[Path]]:
        """Return reference image paths based on current settings, or None."""
        if not self._use_refs_var.get():
            return None
        selected = self._archetype_var.get()
        if selected == "All":
            refs = _get_all_style_refs()
        else:
            refs = _get_archetype_refs(selected)
        return refs if refs else None

    # ── Generation ───────────────────────────────────────────────────────

    def _set_busy(self, busy: bool, status: str = ""):
        self._busy = busy
        self._status_var.set(status)
        state = "disabled" if busy else "normal"
        self._generate_btn.configure(state=state)
        if not busy:
            self._update_result_buttons()
        else:
            for btn in (self._auto_bg_btn, self._manual_btn, self._restore_btn, self._keep_btn, self._save_btn):
                btn.configure(state="disabled")

    def _on_generate(self):
        if self._busy:
            return
        prompt = self._prompt_text.get("1.0", "end").strip()
        if not prompt:
            messagebox.showwarning("No Prompt", "Please enter a prompt.", parent=self.root)
            return

        self._set_busy(True, "Generating...")
        refs = self._get_selected_refs()

        def work():
            try:
                if self._input_image is not None:
                    # img2img mode — encode input to base64 PNG
                    buf = BytesIO()
                    self._input_image.save(buf, format="PNG", compress_level=0, optimize=False)
                    image_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

                    if refs:
                        # img2img + style refs: build custom parts list so
                        # Gemini receives both the input image and reference images.
                        # Refs come first (style context), then the edit task + input image together.
                        parts = [
                            {"text": "These are art style reference images — match their art style for the output:"},
                        ]
                        for ref_path in refs:
                            try:
                                ref_b64 = load_image_as_base64(ref_path)
                                parts.append({"inline_data": {"mime_type": "image/png", "data": ref_b64}})
                            except Exception as e:
                                print(f"[WARN] Could not load reference image {ref_path}: {e}")
                        parts.append({"text": "Edit the image below using these instructions: " + prompt})
                        parts.append({"inline_data": {"mime_type": "image/png", "data": image_b64}})
                        result_bytes = _call_gemini_with_parts(
                            api_key=self._api_key,
                            parts=parts,
                            context="workshop_img2img_refs",
                            skip_background_removal=True,
                        )
                    else:
                        # img2img without refs: use standard image edit
                        result_bytes = call_gemini_image_edit(
                            api_key=self._api_key,
                            prompt=prompt,
                            image_b64=image_b64,
                            skip_background_removal=True,
                        )
                    log_info("WORKSHOP: img2img generation complete")
                else:
                    # txt2img mode — ref images are passed directly
                    result_bytes = call_gemini_text_or_refs(
                        api_key=self._api_key,
                        prompt=prompt,
                        ref_images=refs,
                        skip_background_removal=True,
                    )
                    log_info("WORKSHOP: txt2img generation complete")

                result_img = Image.open(BytesIO(result_bytes)).convert("RGBA")
                self.root.after(0, self._on_generate_done, result_img)

            except Exception as e:
                log_exception(f"WORKSHOP: Generation failed: {e}")
                self.root.after(0, self._on_generate_error, str(e))

        threading.Thread(target=work, daemon=True).start()

    def _on_generate_done(self, result: Image.Image):
        self._raw_result = result
        self._current_result = result.copy()
        self._show_result(result)
        self._set_busy(False, "Done!")

    def _on_generate_error(self, error: str):
        self._set_busy(False, f"Error: {error}")
        messagebox.showerror("Generation Error", f"Gemini call failed:\n{error}", parent=self.root)

    # ── Result display ───────────────────────────────────────────────────

    def _show_result(self, img: Image.Image):
        self._result_tk = _pil_to_tk(img)
        self._result_label.configure(image=self._result_tk, text="", height=0)

    def _update_result_buttons(self):
        has_result = self._current_result is not None
        state = "normal" if has_result else "disabled"
        for btn in (self._auto_bg_btn, self._manual_btn, self._restore_btn, self._keep_btn, self._save_btn):
            btn.configure(state=state)
        # Input save button
        self._save_input_btn.configure(state="normal" if self._input_image is not None else "disabled")

    # ── Background removal ───────────────────────────────────────────────

    def _auto_bg_remove(self):
        if self._busy or self._raw_result is None:
            return
        self._set_busy(True, "Removing background...")

        def work():
            try:
                # Always run on the raw result
                buf = BytesIO()
                self._raw_result.save(buf, format="PNG")
                cleaned_bytes = strip_background_ai(buf.getvalue())
                cleaned_img = Image.open(BytesIO(cleaned_bytes)).convert("RGBA")
                self.root.after(0, self._on_auto_bg_done, cleaned_img)
            except Exception as e:
                log_exception(f"WORKSHOP: Auto BG removal failed: {e}")
                self.root.after(0, self._on_auto_bg_error, str(e))

        threading.Thread(target=work, daemon=True).start()

    def _on_auto_bg_done(self, result: Image.Image):
        self._current_result = result
        self._show_result(result)
        self._set_busy(False, "Background removed!")

    def _on_auto_bg_error(self, error: str):
        self._set_busy(False, f"BG removal error: {error}")
        messagebox.showerror("Error", f"Auto background removal failed:\n{error}", parent=self.root)

    def _manual_bg_remove(self):
        if self._busy or self._current_result is None:
            return
        # Save current result to a temp file for the flood fill tool
        tmp = Path(tempfile.mktemp(suffix=".png"))
        try:
            self._current_result.save(tmp, format="PNG", compress_level=0, optimize=False)
            accepted = click_to_remove_background(tmp, canvas_bg="#ff00ff")
            if accepted:
                # Reload the modified file
                edited = Image.open(tmp).convert("RGBA")
                self._current_result = edited
                self._show_result(edited)
                self._status_var.set("Manual cleanup applied!")
            else:
                self._status_var.set("Manual cleanup cancelled.")
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def _restore_result(self):
        if self._busy or self._raw_result is None:
            return
        self._current_result = self._raw_result.copy()
        self._show_result(self._current_result)
        self._status_var.set("Restored to original.")

    # ── History gallery ────────────────────────────────────────────────

    _HIST_THUMB = 100  # Thumbnail size for gallery items
    _HIST_COLS = 6     # Thumbnails per row

    def _add_to_history(self, img: Image.Image):
        """Add an image to the history gallery."""
        self._history_images.append(img.copy())
        self._rebuild_history_grid()

    def _rebuild_history_grid(self):
        """Rebuild the history thumbnail grid."""
        for w in self._history_frame.winfo_children():
            w.destroy()
        self._history_tks.clear()

        if not self._history_images:
            self._history_placeholder = tk.Label(
                self._history_frame,
                text="Generated images will appear here. Click one to use it as input.",
                bg=BG_COLOR, fg=TEXT_SECONDARY, font=SMALL_FONT,
            )
            self._history_placeholder.pack(anchor="w")
            return

        for idx, img in enumerate(self._history_images):
            row, col = divmod(idx, self._HIST_COLS)
            thumb = img.copy()
            thumb.thumbnail((self._HIST_THUMB, self._HIST_THUMB), Image.Resampling.LANCZOS)
            tk_img = ImageTk.PhotoImage(thumb, master=self.root)
            self._history_tks.append(tk_img)

            lbl = tk.Label(
                self._history_frame, image=tk_img, bg=BG_SECONDARY,
                highlightbackground=CARD_BG, highlightthickness=1, cursor="hand2",
            )
            lbl.grid(row=row, column=col, padx=3, pady=3)
            lbl.bind("<Button-1>", lambda e, i=idx: self._use_history_as_input(i))

    def _use_history_as_input(self, idx: int):
        """Load a history image into the input panel."""
        if self._busy or idx >= len(self._history_images):
            return
        img = self._history_images[idx]
        self._input_image = img.copy()
        self._input_tk = _pil_to_tk(img)
        self._input_label.configure(image=self._input_tk, text="", height=0)
        self._update_result_buttons()
        self._status_var.set(f"Loaded history image #{idx + 1} as input.")

    def _keep_result(self):
        """Add the current result to the history gallery."""
        if self._busy or self._current_result is None:
            return
        self._add_to_history(self._current_result)
        self._status_var.set("Added to history.")

    def _clear_history(self):
        """Clear all history images."""
        if self._busy:
            return
        self._history_images.clear()
        self._history_tks.clear()
        self._rebuild_history_grid()
        self._status_var.set("History cleared.")

    # ── Save ─────────────────────────────────────────────────────────────

    def _save_input(self):
        """Save the current input image to disk."""
        if self._busy or self._input_image is None:
            return
        path = filedialog.asksaveasfilename(
            title="Save input image",
            defaultextension=".png",
            filetypes=[("PNG files", "*.png")],
            parent=self.root,
        )
        if not path:
            return
        try:
            self._input_image.save(path, format="PNG", compress_level=0, optimize=False)
            self._status_var.set(f"Saved to {Path(path).name}")
            log_info(f"WORKSHOP: Saved input to {path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save:\n{e}", parent=self.root)

    def _save_result(self):
        if self._busy or self._current_result is None:
            return
        path = filedialog.asksaveasfilename(
            title="Save result image",
            defaultextension=".png",
            filetypes=[("PNG files", "*.png")],
            parent=self.root,
        )
        if not path:
            return
        try:
            self._current_result.save(path, format="PNG", compress_level=0, optimize=False)
            self._status_var.set(f"Saved to {Path(path).name}")
            log_info(f"WORKSHOP: Saved result to {path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save:\n{e}", parent=self.root)

    # ── Lifecycle ────────────────────────────────────────────────────────

    def _on_close(self):
        self.root.destroy()

    def run(self):
        self.root.mainloop()
