"""
Character upload utility.

Handles uploading character zip files to the SpriteBot database.
"""

from pathlib import Path
from typing import Optional, Tuple

import requests

_BASE_URL = "http://thesaint.servebeer.com:8085"
_UPLOAD_URL = f"{_BASE_URL}/internal/upload"
_CHECK_URL = f"{_BASE_URL}/internal/check-duplicate"
_TRUSTED_APP_KEY = "potatoes"
_TIMEOUT_SECONDS = 120
_CHECK_TIMEOUT_SECONDS = 10


def check_duplicate(char_name: str, username: str) -> Tuple[bool, Optional[bool]]:
    """Check if a character already exists on the SpriteBot database.

    Args:
        char_name: Character folder name to check.
        username: Display name of the uploader.

    Returns:
        (success, exists) tuple.
        success=False means the check itself failed (server unreachable, etc.)
        and the caller should proceed without duplicate handling.
    """
    try:
        resp = requests.get(
            _CHECK_URL,
            headers={"X-Trusted-App-Key": _TRUSTED_APP_KEY},
            params={"name": char_name, "username": username},
            timeout=_CHECK_TIMEOUT_SECONDS,
        )
        if resp.status_code == 200:
            data = resp.json()
            return True, data.get("exists", False)
        return False, None
    except Exception:
        return False, None


def upload_character_zip(
    zip_path: Path, username: str, on_conflict: Optional[str] = None
) -> Tuple[bool, str]:
    """Upload a character zip file to the SpriteBot database.

    Args:
        zip_path: Path to the .zip file to upload.
        username: Display name of the uploader.
        on_conflict: Optional conflict resolution ("replace" or "rename").

    Returns:
        (success, message) tuple.
    """
    try:
        form_data = {"username": username}
        if on_conflict:
            form_data["on_conflict"] = on_conflict

        with open(zip_path, "rb") as f:
            resp = requests.post(
                _UPLOAD_URL,
                headers={"X-Trusted-App-Key": _TRUSTED_APP_KEY},
                files={"zip_file": (zip_path.name, f, "application/zip")},
                data=form_data,
                timeout=_TIMEOUT_SECONDS,
            )

        if resp.status_code in (200, 202):
            return True, "Character uploaded successfully!"
        else:
            return False, f"Server returned status {resp.status_code}: {resp.text}"

    except requests.exceptions.Timeout:
        return False, "Upload timed out. The server may be unavailable."
    except requests.exceptions.ConnectionError:
        return False, "Could not connect to the server. Check your internet connection."
    except Exception as e:
        return False, f"Upload failed: {e}"
