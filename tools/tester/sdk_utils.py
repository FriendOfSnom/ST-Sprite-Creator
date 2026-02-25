"""
SDK Download Utilities for Sprite Tester

Provides functions to download and extract the Ren'Py SDK when not present.
Extracted from src/renpy_scaffolder/sdk_downloader.py for self-containment.
"""

import os
import platform
import shutil
import ssl
import sys
import tarfile
import zipfile
from pathlib import Path
from urllib.request import urlretrieve, urlopen
from urllib.error import URLError
import urllib.request

from sprite_creator.logging_utils import log_info, log_error, log_warning, log_debug

# Ren'Py SDK configuration
SDK_VERSION = "8.5.0"
SDK_FOLDER_NAME = f"renpy-{SDK_VERSION}-sdk"

# Platform-specific download URLs
SDK_URLS = {
    "Windows": "https://www.renpy.org/dl/8.5.0/renpy-8.5.0-sdk.zip",
    "Darwin": "https://www.renpy.org/dl/8.5.0/renpy-8.5.0-sdk.tar.bz2",  # macOS
    "Linux": "https://www.renpy.org/dl/8.5.0/renpy-8.5.0-sdk.tar.bz2",
}


def get_platform() -> str | None:
    """Detect the current platform. Returns None if unsupported."""
    system = platform.system()
    if system in SDK_URLS:
        return system
    print(f"[ERROR] Unsupported platform: {system}")
    print("Supported platforms: Windows, macOS (Darwin), Linux")
    return None


def show_progress(block_num: int, block_size: int, total_size: int) -> None:
    """Display download progress to stdout (if available)."""
    downloaded = block_num * block_size
    if total_size > 0:
        percent = min(downloaded * 100 / total_size, 100)

        size_mb = total_size / (1024 * 1024)
        downloaded_mb = downloaded / (1024 * 1024)

        # Log progress at 10% intervals
        if block_num == 0 or int(percent) % 10 == 0:
            log_debug(f"Download progress: {percent:.0f}% ({downloaded_mb:.1f}/{size_mb:.1f} MB)")

        # Also try to write to stdout for console apps
        try:
            bar_length = 50
            filled = int(bar_length * percent / 100)
            bar = '=' * filled + '-' * (bar_length - filled)
            sys.stdout.write(f'\r[{bar}] {percent:.1f}% ({downloaded_mb:.1f}/{size_mb:.1f} MB)')
            sys.stdout.flush()
        except Exception:
            # GUI mode - stdout may not be available
            pass


def _get_ssl_context():
    """
    Get an SSL context that works in frozen PyInstaller apps.

    PyInstaller bundles may not have SSL certificates accessible,
    so we try multiple approaches.
    """
    # Try 1: Use bundled certifi in frozen app
    if getattr(sys, 'frozen', False):
        # In frozen mode, certifi is bundled at _MEIPASS/certifi/cacert.pem
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            bundled_cert = Path(meipass) / 'certifi' / 'cacert.pem'
            if bundled_cert.exists():
                try:
                    context = ssl.create_default_context(cafile=str(bundled_cert))
                    log_debug(f"Using bundled certifi SSL context: {bundled_cert}")
                    return context
                except Exception as e:
                    log_warning(f"Bundled certifi failed: {e}")

    # Try 2: Use certifi module if available (development mode)
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
        log_debug(f"Using certifi SSL context: {certifi.where()}")
        return context
    except ImportError:
        log_debug("certifi not available, trying default context")
    except Exception as e:
        log_warning(f"certifi SSL context failed: {e}")

    # Try 3: Default SSL context (works in non-frozen apps)
    try:
        context = ssl.create_default_context()
        log_debug("Using default SSL context")
        return context
    except Exception as e:
        log_warning(f"Default SSL context failed: {e}")

    # Try 4: Unverified context (fallback for frozen apps without certs)
    # This is less secure but allows the download to work
    log_warning("Using unverified SSL context (certificates not available)")
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def download_sdk(url: str, output_path: Path) -> bool:
    """
    Download the SDK from the given URL.

    Args:
        url: The download URL
        output_path: Where to save the downloaded file

    Returns:
        True if successful, False otherwise
    """
    log_info(f"Downloading Ren'Py SDK {SDK_VERSION}...")
    log_info(f"URL: {url}")
    log_info(f"Destination: {output_path}")

    try:
        # Set up SSL context that works in frozen apps
        ssl_context = _get_ssl_context()

        # Install custom SSL handler globally for urlretrieve
        https_handler = urllib.request.HTTPSHandler(context=ssl_context)
        opener = urllib.request.build_opener(https_handler)
        urllib.request.install_opener(opener)

        log_info("Starting download (this may take several minutes)...")
        urlretrieve(str(url), str(output_path), reporthook=show_progress)
        log_info("Download complete!")
        return True
    except URLError as e:
        log_error(f"Download failed (URL error): {e}", exc_info=True)
        if "SSL" in str(e) or "CERTIFICATE" in str(e).upper():
            log_error("This appears to be an SSL certificate issue. "
                     "Try installing the 'certifi' package: pip install certifi")
        return False
    except Exception as e:
        log_error(f"Download failed: {e}", exc_info=True)
        return False


def extract_zip(zip_path: Path, extract_to: Path) -> bool:
    """Extract a ZIP file with progress."""
    log_info("Extracting ZIP archive...")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            members = zip_ref.namelist()
            total = len(members)
            log_info(f"Extracting {total} files...")

            for i, member in enumerate(members):
                zip_ref.extract(member, extract_to)
                percent = (i + 1) * 100 / total

                # Log at 10% intervals
                if (i + 1) % max(1, total // 10) == 0:
                    log_debug(f"Extraction progress: {percent:.0f}%")

                try:
                    sys.stdout.write(f'\rExtracting: {percent:.1f}% ({i + 1}/{total} files)')
                    sys.stdout.flush()
                except Exception:
                    pass

        log_info("Extraction complete!")
        return True
    except Exception as e:
        log_error(f"Extraction failed: {e}", exc_info=True)
        return False


def extract_tar(tar_path: Path, extract_to: Path) -> bool:
    """Extract a TAR.BZ2 file with progress."""
    log_info("Extracting TAR.BZ2 archive...")
    try:
        with tarfile.open(tar_path, 'r:bz2') as tar_ref:
            members = tar_ref.getmembers()
            total = len(members)
            log_info(f"Extracting {total} files...")

            for i, member in enumerate(members):
                tar_ref.extract(member, extract_to)
                percent = (i + 1) * 100 / total

                # Log at 10% intervals
                if (i + 1) % max(1, total // 10) == 0:
                    log_debug(f"Extraction progress: {percent:.0f}%")

                try:
                    sys.stdout.write(f'\rExtracting: {percent:.1f}% ({i + 1}/{total} files)')
                    sys.stdout.flush()
                except Exception:
                    pass

        log_info("Extraction complete!")
        return True
    except Exception as e:
        log_error(f"Extraction failed: {e}", exc_info=True)
        return False


def verify_sdk(sdk_path: Path) -> bool:
    """
    Verify that the SDK was extracted correctly.

    Args:
        sdk_path: Path to the extracted SDK folder

    Returns:
        True if verification passes, False otherwise
    """
    log_info("Verifying SDK installation...")

    required_items = ["renpy.py", "launcher"]
    missing = [item for item in required_items if not (sdk_path / item).exists()]

    if missing:
        log_warning(f"Some expected files/folders are missing: {', '.join(missing)}")
        return False

    log_info("SDK verification passed!")
    return True


def download_and_setup_sdk(install_dir: Path) -> bool:
    """
    Download and set up the Ren'Py SDK.

    This is the main entry point for SDK installation.

    Args:
        install_dir: Where to install the SDK (e.g., PROJECT_ROOT/renpy-8.5.0-sdk)

    Returns:
        True if successful, False otherwise
    """
    log_info(f"Starting Ren'Py SDK setup...")
    log_info(f"Install directory: {install_dir}")

    # Get platform
    platform_name = get_platform()
    if not platform_name:
        log_error("Unsupported platform")
        return False

    log_info(f"Detected platform: {platform_name}")

    # Get download URL and file extension
    download_url = SDK_URLS[platform_name]
    file_extension = ".zip" if platform_name == "Windows" else ".tar.bz2"
    download_filename = f"renpy-{SDK_VERSION}-sdk{file_extension}"

    # The parent directory where we'll extract (SDK folder goes inside)
    parent_dir = install_dir.parent
    download_path = parent_dir / download_filename

    log_info(f"Parent directory: {parent_dir}")
    log_info(f"Download path: {download_path}")

    # Ensure parent directory exists
    try:
        parent_dir.mkdir(parents=True, exist_ok=True)
        log_info(f"Parent directory created/verified: {parent_dir}")
    except Exception as e:
        log_error(f"Could not create SDK parent directory {parent_dir}: {e}", exc_info=True)
        return False

    # Check if SDK already exists
    if install_dir.exists():
        log_info(f"SDK already exists at {install_dir}")
        return True

    # Download
    if not download_sdk(download_url, download_path):
        log_error("SDK download failed")
        return False

    # Verify download file exists and has reasonable size
    if not download_path.exists():
        log_error(f"Download file not found: {download_path}")
        return False

    file_size_mb = download_path.stat().st_size / (1024 * 1024)
    log_info(f"Downloaded file size: {file_size_mb:.1f} MB")

    if file_size_mb < 10:
        log_error(f"Downloaded file seems too small ({file_size_mb:.1f} MB), may be corrupted")
        return False

    # Extract
    log_info(f"Extracting to: {parent_dir}")
    if file_extension == ".zip":
        success = extract_zip(download_path, parent_dir)
    else:
        success = extract_tar(download_path, parent_dir)

    if not success:
        log_error("SDK extraction failed")
        return False

    # Verify
    if not verify_sdk(install_dir):
        log_warning("SDK verification failed, but extraction completed - will try anyway")
        # Continue anyway - might still work

    # Cleanup downloaded archive
    log_info("Cleaning up downloaded archive...")
    try:
        download_path.unlink()
        log_info(f"Deleted: {download_filename}")
    except Exception as e:
        log_warning(f"Could not delete archive: {e}")

    log_info("Ren'Py SDK setup complete!")
    return True
