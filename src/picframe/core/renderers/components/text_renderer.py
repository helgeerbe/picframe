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
        self._text_block: pi3d.FixedString | None = None
        self._text_blocks: list[pi3d.FixedString] = []
        self._current_text = ""
        self._current_texts: tuple[str, ...] = ()
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
        """Update the text overlay based on the new configuration."""
        text_strings = tuple(config.text_strings or ())
        if not text_strings and config.text_string:
            text_strings = (config.text_string,)

        if not config.show_text or not any(text_strings):
            self._text_block = None
            self._text_blocks = []
            self._current_text = ""
            self._current_texts = ()
            self._visual_signature = None
            return

        visual_signature = self._build_visual_signature(config, brightness)
        if (
            text_strings != self._current_texts
            or visual_signature != self._visual_signature
            or not self._text_blocks
        ):
            self._logger.debug(f"Rebuilding text overlay: {text_strings}")
            self._current_text = config.text_string
            self._current_texts = text_strings
            self._visual_signature = visual_signature

            font_size = max(8, int(config.show_text_sz))
            margin = max(0, int(config.text_x_margin))
            y_margin = int(config.text_y_margin)
            opacity = int(255 * max(0.0, min(1.0, config.text_opacity)) * brightness)
            justify = str(config.text_justify or "L").upper()
            _, _, render_w, render_h = self._render_bounds()
            render_center_x, render_center_y = self._render_center()
            if justify not in {"L", "C", "R"}:
                justify = "L"
            background_color = None
            if config.text_bkg_hgt > 0:
                background_color = (0, 0, 0, int(255 * 0.45 * brightness))
                band_height = int(render_h * min(max(config.text_bkg_hgt, 0.0), 1.0))
                margin = max(margin, max(5, (band_height - font_size) // 2))

            pair_mode = len(text_strings) == 2
            width = (
                render_w // 2 - (margin * 2)
                if pair_mode
                else render_w - (margin * 2)
            )
            width = max(font_size * 4, width)

            self._text_blocks = []
            
            for index, text in enumerate(text_strings):
                if not text:
                    continue

                text_block = pi3d.FixedString(
                    self._font_file,
                    text,
                    font_size=font_size,
                    shadow_radius=3,
                    shader=self._shader,
                    justify=justify,
                    width=width,
                    margin=5.0,
                    color=(255, 255, 255, opacity),
                    background_color=background_color,
                )

                x = render_center_x
                if pair_mode:
                    pair_offset = render_w // 4
                    x = render_center_x - pair_offset if index == 0 else render_center_x + pair_offset
                y = (
                    render_center_y
                    - (render_h // 2)
                    + (text_block.sprite.height // 2)
                    + y_margin
                )
                text_block.sprite.position(x, y, 0.1)
                text_block.sprite.set_alpha(0.0)
                self._text_blocks.append(text_block)

            self._text_block = self._text_blocks[0] if self._text_blocks else None

    def _build_visual_signature(self, config: OverlayConfig, brightness: float) -> tuple[Any, ...]:
        return (
            int(config.show_text_sz),
            str(config.text_justify or "L").upper(),
            float(config.text_opacity),
            float(config.text_bkg_hgt),
            int(config.text_x_margin),
            int(config.text_y_margin),
            float(brightness),
            self._render_rect,
        )

    def set_alpha(self, alpha: float) -> None:
        """Set the alpha transparency of the text."""
        for text_block in self._text_blocks:
            text_block.sprite.set_alpha(alpha)

    def draw(self) -> None:
        """Draw the text overlay."""
        for text_block in self._text_blocks:
            text_block.sprite.draw()
