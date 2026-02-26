"""
Character upload utility.

Handles uploading character zip files to the SpriteBot database.
"""

from pathlib import Path
from typing import Tuple

import requests

_UPLOAD_URL = "http://thesaint.servebeer.com:8085/internal/upload"
_TRUSTED_APP_KEY = "potatoes"
_TIMEOUT_SECONDS = 120


def upload_character_zip(zip_path: Path, username: str) -> Tuple[bool, str]:
    """Upload a character zip file to the SpriteBot database.

    Args:
        zip_path: Path to the .zip file to upload.
        username: Display name of the uploader.

    Returns:
        (success, message) tuple.
    """
    try:
        with open(zip_path, "rb") as f:
            resp = requests.post(
                _UPLOAD_URL,
                headers={"X-Trusted-App-Key": _TRUSTED_APP_KEY},
                files={"zip_file": (zip_path.name, f, "application/zip")},
                data={"username": username},
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
