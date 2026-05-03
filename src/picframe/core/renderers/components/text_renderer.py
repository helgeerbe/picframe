"""
Text Renderer Component.

Responsible for rendering static text overlays (e.g., image metadata) using pi3d.
"""
import logging
from typing import Any
import pi3d

from picframe.core.events.dto import OverlayConfig


class TextRenderer:
    """Renders text overlays on the pi3d display."""

    def __init__(self, display: Any, shader: Any, font_file: str) -> None:
        self._logger = logging.getLogger(__name__)
        self._display = display
        self._shader = shader
        self._font_file = font_file
        self._text_block: pi3d.FixedString | None = None
        self._current_text = ""

    def update_config(self, config: OverlayConfig, brightness: float = 1.0) -> None:
        """Update the text overlay based on the new configuration."""
        if not config.show_text or not config.text_string:
            self._text_block = None
            self._current_text = ""
            return

        if config.text_string != self._current_text or self._text_block is None:
            self._logger.debug(f"Rebuilding text overlay: {config.text_string}")
            self._current_text = config.text_string
            
            # Default styling (can be expanded via OverlayConfig later)
            font_size = 32
            margin = 20
            opacity = int(255 * 0.8 * brightness)
            
            # Create the FixedString
            self._text_block = pi3d.FixedString(
                self._font_file,
                self._current_text,
                font_size=font_size,
                shadow_radius=3,
                shader=self._shader,
                justify="C",
                width=self._display.width - (margin * 2),
                color=(255, 255, 255, opacity)
            )
            
            # Position at the bottom
            x = 0
            y = - (self._display.height // 2) + (self._text_block.sprite.height // 2) + margin
            self._text_block.sprite.position(x, y, 0.1)
            self._text_block.sprite.set_alpha(0.0)

    def set_alpha(self, alpha: float) -> None:
        """Set the alpha transparency of the text."""
        if self._text_block:
            self._text_block.sprite.set_alpha(alpha)

    def draw(self) -> None:
        """Draw the text overlay."""
        if self._text_block:
            self._text_block.sprite.draw()
