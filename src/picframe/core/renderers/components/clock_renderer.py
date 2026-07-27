"""
Clock Renderer Component.

Responsible for rendering the live clock overlay using pi3d.
"""
import logging
from datetime import datetime
from typing import Any

import pi3d

from picframe.core.events.dto import OverlayConfig


class ClockRenderer:
    """Renders a live clock overlay on the pi3d display."""

    def __init__(
        self,
        display: Any,
        shader: Any,
        font_file: str,
        render_rect: tuple[int, int, int, int] | None = None,
    ) -> None:
        self._logger = logging.getLogger(__name__)
        self._display = display
        self._shader = shader
        self._font_file = font_file
        self._render_rect = render_rect
        self._clock_block: pi3d.FixedString | None = None
        self._current_time_str = ""
        self._current_extra_text = ""
        self._config: OverlayConfig | None = None
        self._brightness = 1.0
        self._visual_signature: tuple[Any, ...] | None = None

    def _render_bounds(self) -> tuple[int, int, int, int]:
        if self._render_rect is not None:
            return self._render_rect
        return (0, 0, int(self._display.width), int(self._display.height))

    def _render_center(self) -> tuple[float, float]:
        x, y, width, height = self._render_bounds()
        if self._render_rect is None:
            return 0.0, 0.0
        center_x = -int(self._display.width) / 2 + x + width / 2
        center_y = int(self._display.height) / 2 - y - height / 2
        return center_x, center_y

    def update_config(self, config: OverlayConfig, brightness: float = 1.0) -> None:
        """Update the clock configuration."""
        visual_signature = self._build_visual_signature(config, brightness)
        if visual_signature != self._visual_signature:
            self._clock_block = None
            self._current_time_str = ""
            self._current_extra_text = ""
            self._visual_signature = visual_signature

        self._config = config
        self._brightness = brightness
        if not config.show_clock:
            self._clock_block = None
            self._current_time_str = ""
            self._current_extra_text = ""

    def _build_visual_signature(self, config: OverlayConfig, brightness: float) -> tuple[Any, ...]:
        return (
            bool(config.show_clock),
            str(config.clock_format),
            str(config.clock_justify or "R").upper(),
            int(config.clock_text_sz),
            float(config.clock_opacity),
            str(config.clock_top_bottom or "T").upper(),
            float(config.clock_wdt_offset_pct),
            float(config.clock_hgt_offset_pct),
            float(brightness),
            self._render_rect,
        )

    def has_changed(self) -> bool:
        """Check if the clock string needs to be updated based on the current time."""
        if not self._config or not self._config.show_clock:
            return False

        try:
            now_str = datetime.now().strftime(self._config.clock_format)
        except Exception:
            now_str = datetime.now().strftime("%H:%M")

        extra_text = self._current_extra_text_from_config()
        return now_str != self._current_time_str or extra_text != self._current_extra_text

    def _current_extra_text_from_config(self) -> str:
        """Return the cached extra text from the current config, stripped."""
        if not self._config:
            return ""
        return str(getattr(self._config, "clock_extra_text", "") or "").strip()

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
        
        extra_text = self._current_extra_text_from_config()
        if (
            now_str != self._current_time_str
            or extra_text != self._current_extra_text
            or self._clock_block is None
        ):
            self._current_time_str = now_str
            self._current_extra_text = extra_text
            display_text = f"{now_str}\n{extra_text}" if extra_text else now_str

            font_size = max(8, int(self._config.clock_text_sz))
            _, _, render_w, render_h = self._render_bounds()
            render_center_x, render_center_y = self._render_center()
            x_margin = int(render_w * max(0.0, self._config.clock_wdt_offset_pct) / 100)
            y_margin = int(render_h * max(0.0, self._config.clock_hgt_offset_pct) / 100)
            opacity = int(
                255 * max(0.0, min(1.0, self._config.clock_opacity)) * self._brightness
            )
            justify = str(self._config.clock_justify or "R").upper()
            if justify not in {"L", "C", "R"}:
                justify = "R"
            
            try:
                self._clock_block = pi3d.FixedString(
                    self._font_file,
                    display_text,
                    font_size=font_size,
                    shadow_radius=3,
                    shader=self._shader,
                    justify=justify,
                    width=max(font_size * 4, render_w - (x_margin * 2)),
                    color=(255, 255, 255, opacity)
                )

                x = render_center_x
                if str(self._config.clock_top_bottom or "T").upper() == "B":
                    y = (
                        render_center_y
                        - (render_h // 2)
                        + (self._clock_block.sprite.height // 2)
                        + y_margin
                    )
                else:
                    y = (
                        render_center_y
                        + (render_h // 2)
                        - (self._clock_block.sprite.height // 2)
                        - y_margin
                    )
                self._clock_block.sprite.position(x, y, 0.1)
            except Exception as e:
                self._logger.error(f"Failed to create clock FixedString: {e}")
                self._clock_block = None
            
        if self._clock_block:
            self._clock_block.sprite.draw()
