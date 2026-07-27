"""
Text Renderer Component.

Responsible for rendering static text overlays (e.g., image metadata) using pi3d.
"""

import logging
from typing import Any

import numpy as np
import pi3d
from PIL import Image

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
        self._background_sprites: list[Any] = []
        self._current_text = ""
        self._current_texts: tuple[str, ...] = ()
        self._current_status_text = ""
        self._visual_signature: tuple[Any, ...] | None = None

    def _get_camera(self) -> Any:
        """Get the active pi3d Camera, creating one if necessary."""
        try:
            camera = pi3d.Camera.instance()
        except AttributeError:
            camera = pi3d.Camera(is_3d=False)
        if camera is None:
            camera = pi3d.Camera(is_3d=False)
        return camera

    def _build_gradient_texture(
        self,
        width: int,
        height: int,
        max_alpha: float,
        brightness: float,
    ) -> Any:
        """Build a numpy-generated RGBA gradient texture with vertical alpha fade."""
        height = max(1, int(height))
        width = max(1, int(width))
        alpha_values = np.linspace(0.0, max_alpha * brightness, height, dtype=np.float32)
        alpha = np.clip(alpha_values, 0.0, 255.0).astype(np.uint8)
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        rgba[:, :, 3] = alpha[:, np.newaxis]
        img = Image.fromarray(rgba, "RGBA")
        return pi3d.Texture(img, blend=True, free_after_load=True)

    def _build_gradient_sprite(
        self,
        sprite_width: int,
        band_height: int,
        max_alpha: float,
        brightness: float,
        center_x: float,
        center_y: float,
    ) -> Any:
        """Build a pi3d.Sprite with a vertical alpha-fade gradient texture."""
        texture = self._build_gradient_texture(sprite_width, band_height, max_alpha, brightness)
        sprite = pi3d.Sprite(
            camera=self._get_camera(),
            w=sprite_width,
            h=band_height,
            z=0.05,
        )
        sprite.set_shader(self._shader)
        sprite.set_textures([texture])
        sprite.position(center_x, center_y, 0.05)
        sprite.set_alpha(0.0)
        return sprite

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
        if not config.show_text:
            text_strings = ()
        status_text = str(config.status_text or "").strip()

        if not any(text_strings) and not status_text:
            self._text_block = None
            self._text_blocks = []
            self._background_sprites = []
            self._current_text = ""
            self._current_texts = ()
            self._current_status_text = ""
            self._visual_signature = None
            return

        visual_signature = self._build_visual_signature(config, brightness)
        if (
            text_strings != self._current_texts
            or status_text != self._current_status_text
            or visual_signature != self._visual_signature
            or not self._text_blocks
        ):
            self._logger.debug(
                "Rebuilding text overlay: %s status=%s",
                text_strings,
                status_text,
            )
            self._current_text = config.text_string
            self._current_texts = text_strings
            self._current_status_text = status_text
            self._visual_signature = visual_signature

            font_size = max(8, int(config.show_text_sz))
            margin = max(0, int(config.text_x_margin))
            y_margin = int(config.text_y_margin) + font_size // 4
            opacity = int(255 * max(0.0, min(1.0, config.text_opacity)) * brightness)
            justify = str(config.text_justify or "L").upper()
            _, _, render_w, render_h = self._render_bounds()
            render_center_x, render_center_y = self._render_center()
            if justify not in {"L", "C", "R"}:
                justify = "L"

            use_gradient = config.text_bkg_hgt > 0
            band_height = 0
            if use_gradient:
                band_height = int(render_h * min(max(config.text_bkg_hgt, 0.0), 1.0))
                margin = max(margin, max(5, (band_height - font_size) // 2))

            pair_mode = len(text_strings) == 2
            width = render_w // 2 - (margin * 2) if pair_mode else render_w - (margin * 2)
            width = max(font_size * 4, width)

            # Justify x offset: subtle positional nudge for non-pair text blocks
            justify_x_offset = 0.0
            if not pair_mode:
                if justify == "L":
                    justify_x_offset = -render_w * 0.02
                elif justify == "R":
                    justify_x_offset = render_w * 0.02

            self._text_blocks = []
            self._background_sprites = []

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
                    background_color=None,
                )

                x = render_center_x + justify_x_offset
                if pair_mode:
                    pair_offset = render_w // 4
                    x = (
                        render_center_x - pair_offset
                        if index == 0
                        else render_center_x + pair_offset
                    )
                y = render_center_y - (render_h // 2) + (text_block.sprite.height // 2) + y_margin
                text_block.sprite.position(x, y, 0.1)
                text_block.sprite.set_alpha(0.0)
                self._text_blocks.append(text_block)

                if use_gradient:
                    grad_width = render_w // 2 if pair_mode else render_w
                    grad_x = x if pair_mode else render_center_x
                    grad_y = render_center_y - render_h // 2 + band_height // 2
                    bg_sprite = self._build_gradient_sprite(
                        sprite_width=grad_width,
                        band_height=band_height,
                        max_alpha=int(255 * 0.45),
                        brightness=brightness,
                        center_x=grad_x,
                        center_y=grad_y,
                    )
                    self._background_sprites.append(bg_sprite)

            if status_text:
                status_block = pi3d.FixedString(
                    self._font_file,
                    status_text,
                    font_size=font_size,
                    shadow_radius=3,
                    shader=self._shader,
                    justify="C",
                    width=max(font_size * 4, render_w - (margin * 2)),
                    margin=5.0,
                    color=(255, 255, 255, opacity),
                    background_color=None,
                )
                status_block.sprite.position(render_center_x, render_center_y, 0.2)
                status_block.sprite.set_alpha(0.0)
                self._text_blocks.append(status_block)

                if use_gradient:
                    bg_sprite = self._build_gradient_sprite(
                        sprite_width=render_w,
                        band_height=band_height,
                        max_alpha=int(255 * 0.45),
                        brightness=brightness,
                        center_x=render_center_x,
                        center_y=render_center_y,
                    )
                    self._background_sprites.append(bg_sprite)

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
        """Set the alpha transparency of the text and background gradient."""
        for sprite in self._background_sprites:
            sprite.set_alpha(alpha)
        for text_block in self._text_blocks:
            text_block.sprite.set_alpha(alpha)

    def draw(self) -> None:
        """Draw the background gradient sprites followed by the text overlay."""
        for sprite in self._background_sprites:
            sprite.draw()
        for text_block in self._text_blocks:
            text_block.sprite.draw()
