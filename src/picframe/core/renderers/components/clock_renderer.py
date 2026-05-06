"""
Clock Renderer Component.

Responsible for rendering the live clock overlay using pi3d.
"""
import logging
import time
from datetime import datetime
from typing import Any
import pi3d

from picframe.core.events.dto import OverlayConfig


class ClockRenderer:
    """Renders a live clock overlay on the pi3d display."""

    def __init__(self, display: Any, shader: Any, font_file: str) -> None:
        self._logger = logging.getLogger(__name__)
        self._display = display
        self._shader = shader
        self._font_file = font_file
        self._clock_block: pi3d.FixedString | None = None
        self._current_time_str = ""
        self._config: OverlayConfig | None = None
        self._brightness = 1.0

    def update_config(self, config: OverlayConfig, brightness: float = 1.0) -> None:
        """Update the clock configuration."""
        self._config = config
        self._brightness = brightness
        if not config.show_clock:
            self._clock_block = None
            self._current_time_str = ""

    def has_changed(self) -> bool:
        """Check if the clock string needs to be updated based on the current time."""
        if not self._config or not self._config.show_clock:
            return False
            
        try:
            now_str = datetime.now().strftime(self._config.clock_format)
        except Exception:
            now_str = datetime.now().strftime("%H:%M")
            
        return now_str != self._current_time_str

    def set_alpha(self, alpha: float) -> None:
        """Set the alpha transparency of the clock."""
        if self._clock_block:
            self._clock_block.sprite.set_alpha(alpha)

    def draw(self) -> None:
        """Draw the clock overlay, updating the string if the time has changed."""
        if not self._config or not self._config.show_clock:
            return

        try:
            now_str = datetime.now().strftime(self._config.clock_format)
        except Exception as e:
            self._logger.error(f"Invalid clock format '{self._config.clock_format}': {e}")
            now_str = datetime.now().strftime("%H:%M")
        
        if now_str != self._current_time_str or self._clock_block is None:
            self._current_time_str = now_str
            
            font_size = 48
            margin = 20
            opacity = int(255 * 0.8 * self._brightness)
            
            try:
                self._clock_block = pi3d.FixedString(
                    self._font_file,
                    self._current_time_str,
                    font_size=font_size,
                    shadow_radius=3,
                    shader=self._shader,
                    justify="R",
                    width=self._display.width - (margin * 2),
                    color=(255, 255, 255, opacity)
                )
                
                # Position at top right
                x = 0
                y = (self._display.height // 2) - (self._clock_block.sprite.height // 2) - margin
                self._clock_block.sprite.position(x, y, 0.1)
            except Exception as e:
                self._logger.error(f"Failed to create clock FixedString: {e}")
                self._clock_block = None
            
        if self._clock_block:
            self._clock_block.sprite.draw()
