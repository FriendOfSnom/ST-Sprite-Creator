"""Custom exceptions for Gemini API errors."""
from typing import List, Optional


class GeminiAPIError(RuntimeError):
    """Base exception for Gemini API errors."""
    pass


class GeminiQuotaError(GeminiAPIError):
    """Raised when API quota is exceeded (billing not enabled or credits exhausted)."""
    pass


class GeminiSafetyError(GeminiAPIError):
    """
    Raised when Gemini blocks content due to safety filters.

    Attributes:
        safety_ratings: List of safety rating dicts from the API response.
    """
    def __init__(self, message: str, safety_ratings: Optional[List[dict]] = None):
        super().__init__(message)
        self.safety_ratings = safety_ratings or []
