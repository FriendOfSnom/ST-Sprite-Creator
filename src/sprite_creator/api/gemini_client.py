"""
Gemini API client for sprite generation.

Handles authentication, API calls, retries, and response parsing for Google Gemini.
"""

import base64
import json
import os
import webbrowser
from io import BytesIO
from pathlib import Path
from typing import List, Optional

import requests
from PIL import Image
from rembg import remove as rembg_remove, new_session as rembg_new_session

from ..config import CONFIG_PATH, GEMINI_API_URL
from ..logging_utils import log_api_call, log_debug, log_info, log_warning, log_error
from .exceptions import GeminiAPIError, GeminiQuotaError, GeminiSafetyError


# =============================================================================
# Background Removal Configuration
# =============================================================================
# Adjust these settings to test different configurations for halo removal.
#
# OPTION A (Current - No alpha matting): Best for clean anime art
#   REMBG_MODEL = "isnet-anime"
#   REMBG_ALPHA_MATTING = False
#   REMBG_POST_PROCESS_MASK = True
#
# OPTION B (Alpha matting with higher erosion): For stubborn halos
#   REMBG_MODEL = "isnet-anime"
#   REMBG_ALPHA_MATTING = True
#   REMBG_ALPHA_MATTING_ERODE_SIZE = 20
#   REMBG_POST_PROCESS_MASK = True
#
# OPTION C (Different model): Try birefnet-general
#   REMBG_MODEL = "birefnet-general"
#   REMBG_ALPHA_MATTING = False
#   REMBG_POST_PROCESS_MASK = True
#
# Available models: isnet-anime, birefnet-general, birefnet-general-lite,
#                   bria-rmbg, u2net, silueta

REMBG_MODEL = "isnet-anime"
REMBG_ALPHA_MATTING = True  # Alpha matting erodes mask edges to reduce halos
REMBG_ALPHA_MATTING_FOREGROUND_THRESHOLD = 220  # Lower — with contrasting BG, rembg is confident about foreground
REMBG_ALPHA_MATTING_BACKGROUND_THRESHOLD = 55   # Higher — semi-transparent leftovers are safely background with contrast
REMBG_ALPHA_MATTING_ERODE_SIZE = 30  # Higher erosion — tested 25-50, 30 is the sweet spot before eating into edges at 40+
REMBG_POST_PROCESS_MASK = True

# Edge cleanup: Remove remaining halo pixels after rembg by color matching
REMBG_EDGE_CLEANUP = True  # Enable edge halo cleanup after AI removal
REMBG_EDGE_CLEANUP_TOLERANCE = 0  # Color distance threshold (0-255, higher=more aggressive)
REMBG_EDGE_CLEANUP_PASSES = 0  # Number of edge cleanup iterations


# =============================================================================
# Configuration Management
# =============================================================================

def load_config() -> dict:
    """
    Load configuration from ~/.st_gemini_config.json if present.

    Returns:
        Dictionary containing configuration, or empty dict if not found.
    """
    if CONFIG_PATH.is_file():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_config(config: dict) -> None:
    """
    Save configuration dictionary to CONFIG_PATH.

    Sets file permissions to 0o600 for security (API keys).

    Args:
        config: Configuration dictionary to save.
    """
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except Exception:
        pass  # Permissions may not be supported on all platforms


def interactive_api_key_setup() -> str:
    """
    Prompt user for Gemini API key and save it to config.

    Opens browser to API key page and prompts for input.

    Returns:
        The API key entered by the user.

    Raises:
        SystemExit: If no API key is entered.
    """
    print("\nIt looks like you haven't configured a Gemini API key yet.")
    print("To use Google Gemini's image model, we need an API key.")
    print("I will open the Gemini API key page in your browser.")
    input("Press Enter to open the Gemini API key page in your browser...")

    key_page_url = "https://aistudio.google.com/app/apikey"
    try:
        webbrowser.open(key_page_url)
    except Exception as e:
        print(f"Warning: could not open browser automatically: {e}")
        print(f"Please open this URL manually in your browser: {key_page_url}")

    api_key = input("\nPaste your Gemini API key here and press Enter:\n> ").strip()
    if not api_key:
        raise SystemExit("No API key entered. Please rerun the script when you have a key.")

    config = load_config()
    config["api_key"] = api_key
    save_config(config)
    print(f"Saved API key to {CONFIG_PATH}.")
    return api_key


def get_api_key(use_gui: bool = True) -> str:
    """
    Return Gemini API key from environment variable or config file.

    Checks GEMINI_API_KEY environment variable first, then config file.
    If neither exists, prompts user interactively (GUI or CLI).

    Args:
        use_gui: If True, use GUI dialog for setup. If False, use CLI.

    Returns:
        Valid Gemini API key.

    Raises:
        SystemExit: If no API key is available and user cancels setup.
    """
    # Check environment variable first
    env_key = os.environ.get("GEMINI_API_KEY")
    if env_key:
        return env_key

    # Check config file
    config = load_config()
    if config.get("api_key"):
        return config["api_key"]

    # Interactive setup if neither exists
    if use_gui:
        try:
            from ..ui.api_setup import show_api_setup
            api_key = show_api_setup()
            if not api_key:
                raise SystemExit("API key setup cancelled. Exiting.")
            return api_key
        except ImportError:
            # Fall back to CLI if GUI module not available
            return interactive_api_key_setup()
    else:
        return interactive_api_key_setup()


# =============================================================================
# Image Utilities
# =============================================================================

def load_image_as_base64(path: Path) -> str:
    """
    Load image from disk, re-encode as PNG, return base64 string.

    Ensures consistent format for Gemini API regardless of source format.

    Args:
        path: Path to image file.

    Returns:
        Base64-encoded PNG image data.
    """
    img = Image.open(path).convert("RGBA")
    buffer = BytesIO()
    img.save(buffer, format="PNG", compress_level=0, optimize=False)
    raw_bytes = buffer.getvalue()
    return base64.b64encode(raw_bytes).decode("utf-8")


def _extract_inline_image_from_response(data: dict) -> Optional[bytes]:
    """
    Extract the first inline image bytes from a Gemini JSON response.

    Handles both 'inlineData' and 'inline_data' field naming.

    Args:
        data: Parsed JSON response from Gemini API.

    Returns:
        Decoded image bytes, or None if no image found.
    """
    candidates = data.get("candidates", [])
    for candidate in candidates:
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            # Handle both naming conventions
            blob = part.get("inlineData") or part.get("inline_data")
            if blob and "data" in blob:
                return base64.b64decode(blob["data"])
    return None


# =============================================================================
# Background Removal
# =============================================================================

# Global session for rembg (reused for performance)
_rembg_session = None


def get_rembg_session():
    """Get or create the rembg session (lazy initialization)."""
    global _rembg_session
    if _rembg_session is None:
        print(f"  [INFO] Initializing AI background removal model: {REMBG_MODEL}...")
        _rembg_session = rembg_new_session(REMBG_MODEL)
    return _rembg_session


def cleanup_edge_halos(
    original_bytes: bytes,
    result_bytes: bytes,
    tolerance: int = 40,
    passes: int = 2
) -> bytes:
    """
    Remove remaining halo pixels by detecting the actual background color.

    Strategy:
    1. DETECT background color by looking at original pixels where rembg made
       them transparent - those pixels were definitely background
    2. Find edge pixels in the rembg result (opaque pixels next to transparent)
    3. Check if edge pixel's ORIGINAL color is close to detected background
    4. If so, make it transparent and check neighbors on next pass

    This approach works even if Gemini doesn't produce exactly #808080.

    Args:
        original_bytes: Original image BEFORE rembg (has solid background)
        result_bytes: Image AFTER rembg (has transparent background)
        tolerance: Color distance threshold (0-255). Higher = more aggressive
        passes: Number of edge layers to process (each pass = 1 pixel deeper)

    Returns:
        PNG image bytes with cleaner edges
    """
    original = Image.open(BytesIO(original_bytes)).convert("RGBA")
    result = Image.open(BytesIO(result_bytes)).convert("RGBA")
    orig_pixels = original.load()
    result_pixels = result.load()
    w, h = result.size

    # Step 1: DETECT background color from pixels rembg made transparent
    # Sample original colors where result is now transparent
    bg_samples_r = []
    bg_samples_g = []
    bg_samples_b = []

    # Sample from corners and edges where background is most likely
    sample_regions = [
        (0, 0, w // 4, h // 4),  # top-left
        (3 * w // 4, 0, w, h // 4),  # top-right
        (0, 0, w, min(50, h // 10)),  # top strip
    ]

    for x1, y1, x2, y2 in sample_regions:
        for y in range(y1, y2):
            for x in range(x1, x2):
                if result_pixels[x, y][3] == 0:  # Now transparent
                    orig_r, orig_g, orig_b, _ = orig_pixels[x, y]
                    bg_samples_r.append(orig_r)
                    bg_samples_g.append(orig_g)
                    bg_samples_b.append(orig_b)

    if not bg_samples_r:
        # Fallback: sample all transparent pixels
        for y in range(h):
            for x in range(w):
                if result_pixels[x, y][3] == 0:
                    orig_r, orig_g, orig_b, _ = orig_pixels[x, y]
                    bg_samples_r.append(orig_r)
                    bg_samples_g.append(orig_g)
                    bg_samples_b.append(orig_b)

    if not bg_samples_r:
        # No transparent pixels - nothing to clean
        return result_bytes

    # Use median to avoid outliers from anti-aliased edges
    bg_samples_r.sort()
    bg_samples_g.sort()
    bg_samples_b.sort()
    mid = len(bg_samples_r) // 2
    bg_r = bg_samples_r[mid]
    bg_g = bg_samples_g[mid]
    bg_b = bg_samples_b[mid]

    print(f"  [INFO] Detected background color: RGB({bg_r}, {bg_g}, {bg_b})")

    # Step 2: Identify edge pixels from rembg result
    original_edges = set()
    for y in range(h):
        for x in range(w):
            if result_pixels[x, y][3] == 0:
                continue  # Skip transparent
            # Check if adjacent to transparent
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h:
                    if result_pixels[nx, ny][3] == 0:
                        original_edges.add((x, y))
                        break

    # Step 3: Process edge pixels in layers
    tolerance_sq = tolerance * tolerance
    total_cleaned = 0
    current_edges = original_edges.copy()

    for pass_num in range(passes):
        if not current_edges:
            break

        edges_to_clear = []
        for x, y in current_edges:
            if result_pixels[x, y][3] == 0:
                continue  # Already removed

            # Check ORIGINAL pixel color against detected background
            orig_r, orig_g, orig_b, _ = orig_pixels[x, y]
            dr = orig_r - bg_r
            dg = orig_g - bg_g
            db = orig_b - bg_b
            dist_sq = dr * dr + dg * dg + db * db

            if dist_sq <= tolerance_sq:
                edges_to_clear.append((x, y))

        # Apply changes and find new edges for next pass
        next_edges = set()
        for x, y in edges_to_clear:
            result_pixels[x, y] = (0, 0, 0, 0)
            # Find neighbors that become new edges
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h:
                    if result_pixels[nx, ny][3] != 0:  # Opaque neighbor
                        next_edges.add((nx, ny))

        total_cleaned += len(edges_to_clear)
        current_edges = next_edges

    if total_cleaned > 0:
        print(f"  [INFO] Edge cleanup removed {total_cleaned} halo pixels")

    buf = BytesIO()
    result.save(buf, format="PNG", compress_level=0, optimize=False)
    return buf.getvalue()


def strip_background_ai(
    image_bytes: bytes,
    skip_edge_cleanup: bool = False,
    edge_cleanup_tolerance: Optional[int] = None,
    edge_cleanup_passes: Optional[int] = None,
) -> bytes:
    """
    Remove background using AI (rembg) with optional edge cleanup.

    Uses configurable model and settings from REMBG_* constants.
    Works with any character colors - no magenta conflicts.
    Uses GPU acceleration if available.

    Args:
        image_bytes: Raw PNG image bytes.
        skip_edge_cleanup: If True, skip the edge cleanup step (useful when
            edge cleanup will be done interactively in the review UI).
        edge_cleanup_tolerance: Custom tolerance for edge cleanup (uses default if None).
        edge_cleanup_passes: Custom passes for edge cleanup (uses default if None).

    Returns:
        PNG image bytes with transparent background.
    """
    try:
        log_debug("Starting AI background removal")
        session = get_rembg_session()
        result = rembg_remove(
            image_bytes,
            session=session,
            alpha_matting=REMBG_ALPHA_MATTING,
            alpha_matting_foreground_threshold=REMBG_ALPHA_MATTING_FOREGROUND_THRESHOLD,
            alpha_matting_background_threshold=REMBG_ALPHA_MATTING_BACKGROUND_THRESHOLD,
            alpha_matting_erode_size=REMBG_ALPHA_MATTING_ERODE_SIZE,
            post_process_mask=REMBG_POST_PROCESS_MASK,
        )

        # Apply edge cleanup to remove remaining halo pixels
        if REMBG_EDGE_CLEANUP and not skip_edge_cleanup:
            tolerance = edge_cleanup_tolerance if edge_cleanup_tolerance is not None else REMBG_EDGE_CLEANUP_TOLERANCE
            passes = edge_cleanup_passes if edge_cleanup_passes is not None else REMBG_EDGE_CLEANUP_PASSES
            result = cleanup_edge_halos(
                original_bytes=image_bytes,
                result_bytes=result,
                tolerance=tolerance,
                passes=passes,
            )

        log_debug("AI background removal completed")
        return result
    except Exception as e:
        log_warning(f"AI background removal failed: {e}")
        print(f"  [WARN] AI background removal failed, returning original: {e}")
        return image_bytes


def strip_background_threshold(image_bytes: bytes) -> bytes:
    """
    Strip background using color threshold (legacy method).

    Only works reliably with magenta backgrounds and characters without pink colors.
    Kept as fallback option.

    Strategy:
      1) Load RGBA.
      2) Collect all opaque border pixels.
      3) Estimate background color as the average of those border pixels.
      4) Clear any pixel sufficiently close to that background color.
    """
    BG_CLEAR_THRESH = 56  # tweak this if it's too aggressive or too gentle

    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGBA")
        w, h = img.size
        pixels = img.load()

        border_samples = []

        # top and bottom rows
        for x in range(w):
            for y in (0, h - 1):
                r, g, b, a = pixels[x, y]
                if a <= 0:
                    continue
                border_samples.append((r, g, b))

        # left and right columns
        for y in range(h):
            for x in (0, w - 1):
                r, g, b, a = pixels[x, y]
                if a <= 0:
                    continue
                border_samples.append((r, g, b))

        if not border_samples:
            # Nothing to go on; just return original
            return image_bytes

        n = float(len(border_samples))
        bg_r = sum(r for r, _, _ in border_samples) / n
        bg_g = sum(g for _, g, _ in border_samples) / n
        bg_b = sum(b for _, _, b in border_samples) / n

        bg_clear_thresh_sq = BG_CLEAR_THRESH * BG_CLEAR_THRESH

        def is_bg(r, g, b):
            dr = r - bg_r
            dg = g - bg_g
            db = b - bg_b
            return (dr * dr + dg * dg + db * db) <= bg_clear_thresh_sq

        out = Image.new("RGBA", (w, h))
        out_pixels = out.load()

        for y in range(h):
            for x in range(w):
                r, g, b, a = pixels[x, y]
                if a <= 0:
                    out_pixels[x, y] = (r, g, b, 0)
                elif is_bg(r, g, b):
                    out_pixels[x, y] = (r, g, b, 0)
                else:
                    out_pixels[x, y] = (r, g, b, a)

        buf = BytesIO()
        out.save(buf, format="PNG", compress_level=0, optimize=False)
        return buf.getvalue()

    except Exception as e:
        print(f"  [WARN] strip_background failed, returning original bytes: {e}")
        return image_bytes


# =============================================================================
# Gemini API Calls
# =============================================================================

def _call_gemini_with_parts(
    api_key: str,
    parts: List[dict],
    context: str,
    skip_background_removal: bool = False,
    edge_cleanup_tolerance: Optional[int] = None,
    edge_cleanup_passes: Optional[int] = None,
) -> bytes:
    """
    Call Gemini API with custom parts array and retry logic.

    Handles retries for transient errors (429, 500, 502, 503, 504).
    Applies AI background removal to returned images unless skipped.

    Args:
        api_key: Google Gemini API key.
        parts: List of content parts (text, images, etc.).
        context: Description of the operation for error messages.
        skip_background_removal: If True, return raw image without background removal.
        edge_cleanup_tolerance: Custom tolerance for edge cleanup (uses default if None).
        edge_cleanup_passes: Custom passes for edge cleanup (uses default if None).

    Returns:
        Image bytes (with transparent background unless skip_background_removal=True).

    Raises:
        RuntimeError: If API call fails after all retries.
    """
    payload = {"contents": [{"parts": parts}]}
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    max_retries = 3
    last_error = None

    log_debug(f"Gemini API call starting: {context}")

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(
                GEMINI_API_URL,
                headers=headers,
                data=json.dumps(payload)
            )

            # Handle retryable errors
            if not response.ok:
                if response.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    log_warning(f"Gemini API error {response.status_code} ({context}) attempt {attempt}, retrying...")
                    print(
                        f"[WARN] Gemini API error {response.status_code} ({context}) "
                        f"attempt {attempt}; retrying..."
                    )
                    last_error = f"Gemini API error {response.status_code}: {response.text}"
                    continue
                log_api_call(context, False, f"HTTP {response.status_code}: {response.text[:200]}")
                # Provide a user-friendly message for quota/billing errors
                if response.status_code == 429:
                    resp_text = response.text.lower()
                    if "free_tier" in resp_text or "quota" in resp_text:
                        raise GeminiQuotaError(
                            "API quota exceeded.\n\n"
                            "This usually means you're using a free-tier API key.\n"
                            "You need a Google Cloud API key with billing enabled.\n\n"
                            "Go to console.cloud.google.com > Billing to enable billing.\n"
                            "New Google Cloud accounts get $300 in free credits.\n"
                            "Check API Settings on the launcher to update your key."
                        )
                    else:
                        raise GeminiAPIError(
                            "Rate limited by Google API.\n\n"
                            "Too many requests in a short period.\n"
                            "Please wait a minute and try again."
                        )
                raise GeminiAPIError(f"Gemini API error {response.status_code}: {response.text}")

            data = response.json()

            # Check for safety blocking before extracting image
            candidates = data.get("candidates", [])
            for candidate in candidates:
                finish_reason = candidate.get("finishReason")
                if finish_reason in ("SAFETY", "IMAGE_SAFETY", "IMAGE_OTHER"):
                    safety_ratings = candidate.get("safetyRatings", [])
                    log_api_call(context, False, f"Safety blocked: {finish_reason}")
                    raise GeminiSafetyError(
                        f"Content blocked by safety filters ({context}): {finish_reason}",
                        safety_ratings
                    )

            raw_bytes = _extract_inline_image_from_response(data)

            if raw_bytes is not None:
                log_api_call(context, True, f"Image received ({len(raw_bytes)} bytes)")
                if skip_background_removal:
                    return raw_bytes
                # Apply AI background removal with optional custom settings
                return strip_background_ai(
                    raw_bytes,
                    edge_cleanup_tolerance=edge_cleanup_tolerance,
                    edge_cleanup_passes=edge_cleanup_passes,
                )

            # Log the full response to diagnose why there's no image
            log_debug(f"Gemini response without image data: {json.dumps(data, indent=2)[:500]}")
            print(f"[DEBUG] Gemini response without image data:")
            print(f"[DEBUG] Full response: {json.dumps(data, indent=2)}")

            last_error = f"No image data in Gemini response ({context})."
            if attempt < max_retries:
                log_warning(f"Gemini response missing image ({context}) attempt {attempt}, retrying...")
                print(
                    f"[WARN] Gemini response missing image ({context}) "
                    f"attempt {attempt}; retrying..."
                )
                continue
            log_api_call(context, False, "No image data in response")
            raise GeminiAPIError(last_error)

        except GeminiSafetyError:
            # Safety errors are not transient - don't retry, let caller handle with different prompt
            raise
        except Exception as e:
            last_error = str(e)
            if attempt < max_retries:
                log_warning(f"Gemini call failed ({context}) attempt {attempt}: {e}")
                print(
                    f"[WARN] Gemini call failed ({context}) "
                    f"attempt {attempt}; retrying: {e}"
                )
                continue
            log_api_call(context, False, f"Failed after {max_retries} attempts: {last_error}")
            raise GeminiAPIError(
                f"Gemini call failed after {max_retries} attempts ({context}): {last_error}"
            )


def call_gemini_image_edit(
    api_key: str,
    prompt: str,
    image_b64: str,
    skip_background_removal: bool = False,
    edge_cleanup_tolerance: Optional[int] = None,
    edge_cleanup_passes: Optional[int] = None,
) -> bytes:
    """
    Call Gemini image model with an input image and text prompt for editing.

    AI background removal is automatically applied to the result unless skipped.

    Args:
        api_key: Google Gemini API key.
        prompt: Text prompt describing the desired edit.
        image_b64: Base64-encoded input image.
        skip_background_removal: If True, return raw image without background removal.
        edge_cleanup_tolerance: Custom tolerance for edge cleanup (uses default if None).
        edge_cleanup_passes: Custom passes for edge cleanup (uses default if None).

    Returns:
        Generated/edited image bytes (with transparent background unless skipped).
    """
    log_info(f"GEMINI: image_edit prompt ({len(prompt)} chars): {prompt[:200]}...")
    log_debug(f"GEMINI: Full image_edit prompt: {prompt}")
    parts: List[dict] = [
        {"text": prompt},
        {"inline_data": {"mime_type": "image/png", "data": image_b64}},
    ]
    return _call_gemini_with_parts(
        api_key, parts, "image_edit", skip_background_removal,
        edge_cleanup_tolerance, edge_cleanup_passes
    )


def call_gemini_text(
    api_key: str,
    prompt: str,
    temperature: float = 1.0,
) -> str:
    """
    Call Gemini text API and return the response text.

    Used for generating outfit descriptions dynamically.

    Args:
        api_key: Google Gemini API key.
        prompt: Text prompt to send.
        temperature: Sampling temperature (0.0-2.0, default 1.0).

    Returns:
        Generated text response.

    Raises:
        GeminiAPIError: If API call fails.
    """
    # Use text model, not image model
    text_model = "gemini-2.0-flash"
    text_url = f"https://generativelanguage.googleapis.com/v1beta/models/{text_model}:generateContent"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature}
    }
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key
    }

    try:
        log_info(f"GEMINI: text prompt ({len(prompt)} chars, temp={temperature}): {prompt[:200]}...")
        log_debug(f"GEMINI: Full text prompt: {prompt}")
        response = requests.post(text_url, headers=headers, json=payload)

        if not response.ok:
            log_api_call("text_generation", False, f"HTTP {response.status_code}")
            raise GeminiAPIError(f"Gemini text API error {response.status_code}: {response.text[:200]}")

        data = response.json()

        # Extract text from response
        candidates = data.get("candidates", [])
        if candidates:
            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            if parts:
                result = parts[0].get("text", "").strip()
                log_api_call("text_generation", True, f"Got {len(result)} chars")
                return result

        log_api_call("text_generation", False, "No text in response")
        raise GeminiAPIError("No text in Gemini response")

    except GeminiAPIError:
        raise
    except Exception as e:
        log_api_call("text_generation", False, str(e))
        raise GeminiAPIError(f"Gemini text API call failed: {e}")


def call_gemini_fusion(
    api_key: str,
    prompt: str,
    left_image_b64: str,
    right_image_b64: str,
    skip_background_removal: bool = False,
    edge_cleanup_tolerance: Optional[int] = None,
    edge_cleanup_passes: Optional[int] = None,
) -> bytes:
    """
    Call Gemini image model with two input images for character fusion.

    Creates a new character that combines features from both input images.
    AI background removal is automatically applied to the result unless skipped.

    Args:
        api_key: Google Gemini API key.
        prompt: Text prompt describing the desired fusion.
        left_image_b64: Base64-encoded left character image.
        right_image_b64: Base64-encoded right character image.
        skip_background_removal: If True, return raw image without background removal.
        edge_cleanup_tolerance: Custom tolerance for edge cleanup (uses default if None).
        edge_cleanup_passes: Custom passes for edge cleanup (uses default if None).

    Returns:
        Generated/fused image bytes (with transparent background unless skipped).
    """
    log_info(f"GEMINI: fusion prompt ({len(prompt)} chars): {prompt[:200]}...")
    log_debug(f"GEMINI: Full fusion prompt: {prompt}")
    parts: List[dict] = [
        {"text": prompt},
        {"inline_data": {"mime_type": "image/png", "data": left_image_b64}},
        {"inline_data": {"mime_type": "image/png", "data": right_image_b64}},
    ]
    return _call_gemini_with_parts(
        api_key, parts, "fusion", skip_background_removal,
        edge_cleanup_tolerance, edge_cleanup_passes
    )


def call_gemini_text_or_refs(
    api_key: str,
    prompt: str,
    ref_images: Optional[List[Path]] = None,
    skip_background_removal: bool = False,
    edge_cleanup_tolerance: Optional[int] = None,
    edge_cleanup_passes: Optional[int] = None,
) -> bytes:
    """
    Call Gemini with a text prompt and optional reference images.

    Used for generating new characters from text descriptions with
    style references. AI background removal is automatically applied unless skipped.

    Args:
        api_key: Google Gemini API key.
        prompt: Text prompt describing what to generate.
        ref_images: Optional list of reference image paths for style guidance.
        skip_background_removal: If True, return raw image without background removal.
        edge_cleanup_tolerance: Custom tolerance for edge cleanup (uses default if None).
        edge_cleanup_passes: Custom passes for edge cleanup (uses default if None).

    Returns:
        Generated image bytes (with transparent background unless skipped).
    """
    log_info(f"GEMINI: text_or_refs prompt ({len(prompt)} chars, refs={len(ref_images) if ref_images else 0}): {prompt[:200]}...")
    log_debug(f"GEMINI: Full text_or_refs prompt: {prompt}")
    parts: List[dict] = [{"text": prompt}]

    # Add reference images if provided
    if ref_images:
        for ref_path in ref_images:
            try:
                ref_b64 = load_image_as_base64(ref_path)
                parts.append({
                    "inline_data": {"mime_type": "image/png", "data": ref_b64}
                })
            except Exception as e:
                print(f"[WARN] Could not load reference image {ref_path}: {e}")

    return _call_gemini_with_parts(
        api_key, parts, "text_or_refs", skip_background_removal,
        edge_cleanup_tolerance, edge_cleanup_passes
    )
