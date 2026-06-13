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
        self._text_blocks: list[pi3d.FixedString] = []
        self._current_text = ""
        self._current_texts: tuple[str, ...] = ()

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
            return

        if text_strings != self._current_texts or not self._text_blocks:
            self._logger.debug(f"Rebuilding text overlay: {text_strings}")
            self._current_text = config.text_string
            self._current_texts = text_strings

            font_size = max(8, int(config.show_text_sz))
            margin = max(0, int(config.text_x_margin))
            y_margin = int(config.text_y_margin)
            opacity = int(255 * max(0.0, min(1.0, config.text_opacity)) * brightness)
            justify = str(config.text_justify or "L").upper()
            if justify not in {"L", "C", "R"}:
                justify = "L"
            background_color = None
            if config.text_bkg_hgt > 0:
                background_color = (0, 0, 0, int(255 * 0.45 * brightness))
                band_height = int(self._display.height * min(max(config.text_bkg_hgt, 0.0), 1.0))
                margin = max(margin, max(5, (band_height - font_size) // 2))

            pair_mode = len(text_strings) == 2
            width = (
                self._display.width // 2 - (margin * 2)
                if pair_mode
                else self._display.width - (margin * 2)
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

                x = 0
                if pair_mode:
                    x = -self._display.width // 4 if index == 0 else self._display.width // 4
                y = - (self._display.height // 2) + (text_block.sprite.height // 2) + y_margin
                text_block.sprite.position(x, y, 0.1)
                text_block.sprite.set_alpha(0.0)
                self._text_blocks.append(text_block)

            self._text_block = self._text_blocks[0] if self._text_blocks else None

    def set_alpha(self, alpha: float) -> None:
        """Set the alpha transparency of the text."""
        for text_block in self._text_blocks:
            text_block.sprite.set_alpha(alpha)

    def draw(self) -> None:
        """Draw the text overlay."""
        for text_block in self._text_blocks:
            text_block.sprite.draw()
