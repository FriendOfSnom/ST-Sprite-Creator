"""
Base classes for wizard step architecture.

Provides the WizardStep abstract base class for the unified sprite creation wizard.
The WizardState data container is imported from core/models.py.
"""

import tkinter as tk
from abc import ABC, abstractmethod
from typing import List, Optional, TYPE_CHECKING

# Import WizardState from core layer
from ...core.models import WizardState
from ...config import BG_COLOR, WARNING_TEXT, SMALL_FONT

if TYPE_CHECKING:
    from ..full_wizard import FullWizard


class WizardStep(ABC):
    """
    Abstract base class for wizard steps.

    Each step handles one phase of the sprite creation process. Steps are
    responsible for building their UI, validating input, and managing their
    portion of the wizard state.

    Lifecycle:
        1. build_ui() - Called once when step is created
        2. on_enter() - Called each time step becomes active
        3. User interacts with step
        4. validate() - Called before advancing to next step
        5. on_leave() - Called when navigating away from step
    """

    # Step metadata - override in subclasses
    STEP_ID: str = "base"
    STEP_TITLE: str = "Base Step"
    STEP_NUMBER: int = 0  # Hardcoded step number for consistent display
    STEP_HELP: str = "Override this help text in subclass."
    STEP_TIP: str = ""  # Short tip shown below the title on every screen

    def __init__(self, wizard: "FullWizard", state: WizardState):
        """
        Initialize the wizard step.

        Args:
            wizard: Parent wizard controller for navigation callbacks.
            state: Shared wizard state container.
        """
        self.wizard = wizard
        self.state = state
        self._frame: Optional[tk.Frame] = None
        self._is_built = False

    @property
    def frame(self) -> Optional[tk.Frame]:
        """Get the step's main frame, if built."""
        return self._frame

    def build(self, parent: tk.Frame) -> tk.Frame:
        """
        Build the step's UI and return its frame.

        This is called once during wizard initialization. The frame is
        hidden/shown as the user navigates between steps.

        Args:
            parent: Parent frame to contain this step's UI.

        Returns:
            The step's main frame.
        """
        self._frame = tk.Frame(parent)
        self.build_ui(self._frame)
        self._is_built = True
        return self._frame

    @abstractmethod
    def build_ui(self, parent: tk.Frame) -> None:
        """
        Build the step's UI components.

        Override this method to create all UI elements for the step.
        The parent frame uses the wizard's dark theme styling.

        Args:
            parent: Frame to contain all step UI elements.
        """
        pass

    @abstractmethod
    def validate(self) -> bool:
        """
        Validate the step's data before advancing.

        Called when user clicks Next. Return True to allow advancing,
        False to stay on current step (should show error message).

        Returns:
            True if validation passes, False otherwise.
        """
        pass

    def on_enter(self) -> None:
        """
        Called when the step becomes active.

        Override to perform actions when navigating to this step, such as:
        - Refreshing displayed data from state
        - Starting generation processes
        - Setting initial focus

        Default implementation does nothing.
        """
        pass

    def on_leave(self) -> None:
        """
        Called when navigating away from this step.

        Override to perform cleanup or save intermediate state.
        Called for both forward and backward navigation.

        Default implementation does nothing.
        """
        pass

    def is_dirty(self) -> bool:
        """
        Check if this step has unsaved changes that invalidate later steps.

        Override in steps that collect data affecting generation.
        Used to warn user when navigating back might lose work.

        Returns:
            True if step has changes that invalidate later generated content.
        """
        return False

    def get_dirty_steps(self) -> List[int]:
        """
        Get list of step indices that would be invalidated by changes here.

        Override to specify which later steps need regeneration if this
        step's data changes.

        Returns:
            List of step indices (0-based) that would need regeneration.
        """
        return []

    def should_skip(self) -> bool:
        """
        Check if this step should be skipped in the current flow.

        Override for conditional steps that only apply in certain modes.
        For example, the crop step might be skipped if image is already cropped.

        Returns:
            True if step should be skipped, False to show it.
        """
        return False

    def show_loading(self, message: str = "Loading...") -> None:
        """
        Show a loading indicator for long-running operations.

        Call this before starting generation or other async work.
        Call hide_loading() when done.

        Args:
            message: Text to display during loading.
        """
        if self.wizard:
            self.wizard.show_loading(message)

    def hide_loading(self) -> None:
        """Hide the loading indicator."""
        if self.wizard:
            self.wizard.hide_loading()

    def schedule_callback(self, callback) -> None:
        """
        Schedule a callback on the main thread (thread-safe).

        Background threads must use this instead of self.wizard.root.after()
        to avoid tkinter thread-safety issues on some Windows systems.
        """
        if self.wizard:
            self.wizard.schedule_callback(callback)

    def update_display(self) -> None:
        """
        Refresh the step's display from current state.

        Override to update UI elements when state changes externally,
        such as after regeneration.
        """
        pass

    def _build_tip_bar(self, parent: tk.Frame) -> None:
        """Build a standardized tip bar below the step title."""
        if not self.STEP_TIP:
            return
        tip_text = self.STEP_TIP
        if "{bg_color}" in tip_text:
            from ...config import load_background_color
            bg_color_name = load_background_color().split("(")[0].strip()
            tip_text = tip_text.replace("{bg_color}", bg_color_name)
        self._tip_label = tk.Label(
            parent,
            text=tip_text,
            bg=BG_COLOR,
            fg=WARNING_TEXT,
            font=SMALL_FONT,
            wraplength=800,
            justify="center",
        )
        self._tip_label.pack(pady=(0, 8))

    def _update_tip(self, text: str) -> None:
        """Update the tip bar text dynamically (e.g. for mode-specific tips)."""
        if hasattr(self, "_tip_label") and self._tip_label:
            self._tip_label.configure(text=text)

    def request_next(self) -> None:
        """Request navigation to the next step."""
        if self.wizard:
            self.wizard.go_next()

    def request_back(self) -> None:
        """Request navigation to the previous step."""
        if self.wizard:
            self.wizard.go_back()
