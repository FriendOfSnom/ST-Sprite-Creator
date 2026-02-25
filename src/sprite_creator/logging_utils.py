"""
Logging utilities for AI Sprite Creator.

Provides file-based logging that:
- Writes to logs/sprite_creator.log (location depends on how the app is run)
- Wipes the log on each program restart
- Captures uncaught exceptions
- Logs key events (API calls, generation, errors)
"""

import logging
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import APP_NAME, APP_VERSION


def _get_log_dir() -> Path:
    """Get the log directory.

    - Frozen (PyInstaller): next to the executable
    - AppImage: ~/.sprite_creator/logs/
    - Development: project root /logs/
    """
    if getattr(sys, 'frozen', False):
        # Frozen .exe - put logs next to the executable
        return Path(sys.executable).parent / "logs"
    elif os.environ.get('APPIMAGE'):
        # AppImage - put logs next to the .AppImage file (like Windows puts them next to .exe)
        return Path(os.environ['APPIMAGE']).parent / "logs"
    else:
        # Development - use project root (parent of src/)
        return Path(__file__).resolve().parent.parent.parent / "logs"


# Log directory and file
LOG_DIR = _get_log_dir()
LOG_FILE = LOG_DIR / "sprite_creator.log"

# Module-level logger
_logger: Optional[logging.Logger] = None
_initialized = False


def _ensure_log_dir() -> None:
    """Ensure the log directory exists."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[WARN] Could not create log directory: {e}")


def setup_logging() -> logging.Logger:
    """
    Initialize the logging system.

    Call this once at application startup. The log file is wiped on each restart.

    Returns:
        The configured logger instance.
    """
    global _logger, _initialized

    if _initialized and _logger:
        return _logger

    _ensure_log_dir()

    # Create logger
    _logger = logging.getLogger("sprite_creator")
    _logger.setLevel(logging.DEBUG)

    # Clear any existing handlers
    _logger.handlers.clear()

    # File handler - 'w' mode wipes the file on each restart
    try:
        file_handler = logging.FileHandler(
            LOG_FILE,
            mode='w',  # Wipe on restart
            encoding='utf-8',
        )
        file_handler.setLevel(logging.DEBUG)

        # Format: timestamp - level - message
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        _logger.addHandler(file_handler)
    except Exception as e:
        print(f"[WARN] Could not set up file logging: {e}")

    # Also log to console in debug mode (when not frozen)
    if not getattr(sys, 'frozen', False):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter('%(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        _logger.addHandler(console_handler)

    # Log startup info
    _logger.info("=" * 60)
    _logger.info(f"{APP_NAME} v{APP_VERSION} started")
    _logger.info(f"Log file: {LOG_FILE}")
    _logger.info(f"Python version: {sys.version}")
    _logger.info(f"Frozen: {getattr(sys, 'frozen', False)}")
    _logger.info("=" * 60)

    # Set up uncaught exception handler
    _setup_exception_handler()

    _initialized = True
    return _logger


def _setup_exception_handler() -> None:
    """Set up global exception handler to log uncaught exceptions."""
    original_excepthook = sys.excepthook

    def exception_handler(exc_type, exc_value, exc_traceback):
        # Don't log KeyboardInterrupt
        if issubclass(exc_type, KeyboardInterrupt):
            original_excepthook(exc_type, exc_value, exc_traceback)
            return

        # Log the exception
        if _logger:
            _logger.critical("Uncaught exception:", exc_info=(exc_type, exc_value, exc_traceback))

        # Call the original handler
        original_excepthook(exc_type, exc_value, exc_traceback)

    sys.excepthook = exception_handler


def get_logger() -> logging.Logger:
    """
    Get the logger instance. Initializes logging if not already done.

    Returns:
        The logger instance.
    """
    global _logger
    if not _initialized:
        return setup_logging()
    return _logger


# Convenience functions for direct logging
def log_debug(message: str) -> None:
    """Log a debug message."""
    get_logger().debug(message)


def log_info(message: str) -> None:
    """Log an info message."""
    get_logger().info(message)


def log_warning(message: str) -> None:
    """Log a warning message."""
    get_logger().warning(message)


def log_error(message: str, detail: str = "", exc_info: bool = False) -> None:
    """
    Log an error message.

    Args:
        message: The error message (or context label if detail is provided)
        detail: Optional detail string appended after ": "
        exc_info: If True, include exception traceback
    """
    if detail:
        message = f"{message}: {detail}"
    get_logger().error(message, exc_info=exc_info)


def log_exception(message: str) -> None:
    """Log an error with full exception traceback."""
    get_logger().exception(message)


def log_api_call(endpoint: str, success: bool, details: str = "") -> None:
    """
    Log an API call for debugging.

    Args:
        endpoint: The API endpoint or operation name
        success: Whether the call succeeded
        details: Additional details (error message, etc.)
    """
    status = "SUCCESS" if success else "FAILED"
    msg = f"API [{status}] {endpoint}"
    if details:
        msg += f" - {details}"

    if success:
        get_logger().info(msg)
    else:
        get_logger().error(msg)


def log_generation_start(gen_type: str, count: int = 1) -> None:
    """Log the start of a generation operation."""
    get_logger().info(f"Generation started: {gen_type} (count={count})")


def log_generation_complete(gen_type: str, success: bool, details: str = "") -> None:
    """Log the completion of a generation operation."""
    status = "completed" if success else "failed"
    msg = f"Generation {status}: {gen_type}"
    if details:
        msg += f" - {details}"

    if success:
        get_logger().info(msg)
    else:
        get_logger().error(msg)


def get_log_file_path() -> Path:
    """Get the path to the log file."""
    return LOG_FILE


def get_log_contents() -> str:
    """
    Read and return the current log file contents.

    Useful for displaying logs to the user or copying to clipboard.
    """
    try:
        if LOG_FILE.exists():
            return LOG_FILE.read_text(encoding='utf-8')
        return "(Log file not found)"
    except Exception as e:
        return f"(Error reading log: {e})"
