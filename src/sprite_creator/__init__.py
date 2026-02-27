"""
ST Sprite Creator

AI-powered character sprite generator using Google Gemini vision models.
Provides a full wizard interface for creating visual novel character sprites.

Package Structure:
    core/       - Business logic and data models
    api/        - Gemini API integration
    processing/ - Image generation and manipulation
    ui/         - Tkinter user interface
    utils/      - Shared utilities
    tools/      - Standalone tools (tester, expression sheets)
    tester/     - Ren'Py sprite testing
"""

__version__ = "1.2.0"

# Lazy imports for heavy dependencies
def __getattr__(name):
    if name == "WizardState":
        from .core.models import WizardState
        return WizardState
    if name == "CharacterConfig":
        from .core.models import CharacterConfig
        return CharacterConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "__version__",
    "WizardState",
    "CharacterConfig",
]
