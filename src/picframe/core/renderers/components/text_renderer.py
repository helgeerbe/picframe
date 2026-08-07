"""
Text Renderer Component.

Responsible for rendering static text overlays (e.g., image metadata) using pi3d.
"""

import logging
from typing import Any

import numpy as np
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
        self._background_sprites: list[Any] = []
        self._gradient_texture: Any = None
        self._gradient_texture_sig: tuple[Any, ...] | None = None
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
        height: int,
        max_alpha: float,
        brightness: float,
    ) -> Any:
        """Build a 1px-wide RGBA gradient texture with vertical alpha fade.

        Bug 1b: pass numpy array directly to ``pi3d.Texture`` (no PIL conversion).
        Bug 1c: texture is 1px wide; width is applied via GPU ``sprite.scale()``.
        Paddy's #719 feedback: texture is built at full render height for a
        smoother gradient; the sprite is scaled down to ``band_height`` via GPU.
        """
        height = max(1, int(height))
        alpha_values = np.linspace(0.0, max_alpha * brightness, height, dtype=np.float32)
        alpha = np.clip(alpha_values, 0.0, 255.0).astype(np.uint8)
        rgba = np.zeros((height, 1, 4), dtype=np.uint8)
        rgba[:, :, 3] = alpha[:, np.newaxis]
        return pi3d.Texture(rgba, blend=True, free_after_load=True)

    def _get_gradient_texture(
        self,
        texture_height: int,
        max_alpha: float,
        brightness: float,
    ) -> Any:
        """Return cached gradient texture, rebuilding only when signature changes (Bug 1c).

        *texture_height* is the full render height (not band height); the sprite
        is scaled to ``band_height`` via GPU so the texture is not rebuilt when
        only the band height changes.
        """
        sig = (int(texture_height), int(max_alpha), round(float(brightness), 6))
        if self._gradient_texture is not None and sig == self._gradient_texture_sig:
            return self._gradient_texture
        self._gradient_texture = self._build_gradient_texture(texture_height, max_alpha, brightness)
        self._gradient_texture_sig = sig
        return self._gradient_texture

    def _adjust_gradient_sprites(
        self,
        texture: Any,
        specs: list[tuple[int, float, float]],
        band_height: int,
    ) -> list[Any]:
        """Reuse cached gradient sprites, creating/removing only as needed (Bug 1c).

        *specs* is a list of ``(sprite_width, center_x, center_y)`` tuples.
        Sprites are created with ``w=1, h=1`` and scaled via GPU (Bug 1a/1c).
        """
        sprites = self._background_sprites
        needed = len(specs)

        while len(sprites) > needed:
            sprites.pop()

        while len(sprites) < needed:
            # Bug 1a: no z in constructor — z is set only via position()
            sprite = pi3d.Sprite(camera=self._get_camera(), w=1, h=1)
            sprite.set_shader(self._shader)
            sprite.set_alpha(0.0)
            sprites.append(sprite)

        # z increases away from the camera (Paddy's #719 feedback).
        # Gradient must be BEHIND text (z=0.3 > text z=0.1) so text is visible.
        for sprite, (sprite_width, cx, cy) in zip(sprites, specs):
            sprite.set_textures([texture])
            sprite.position(cx, cy, 0.3)  # Bug 1a: z only in position(); #719 z-order
            sprite.scale(sprite_width, band_height, 1.0)  # Bug 1c: GPU scaling

        return sprites

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

            self._text_blocks = []
            gradient_specs: list[tuple[int, float, float]] = []

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

                # #728: edge-based x positioning for L/R justify — text sits at the
                # render-area edge (or pair-half edge) rather than near the center.
                x = render_center_x
                if pair_mode:
                    pair_offset = render_w // 4
                    if index == 0:
                        x -= pair_offset
                    else:
                        x += pair_offset

                if justify in ("L", "R"):
                    justify_offset = width // 2 - text_block.sprite.width // 2
                    if justify == "L":
                        x -= justify_offset
                    else:
                        x += justify_offset

                y = render_center_y - (render_h // 2) + (text_block.sprite.height // 2) + y_margin
                text_block.sprite.position(x, y, 0.1)
                text_block.sprite.set_alpha(0.0)
                self._text_blocks.append(text_block)

                if use_gradient:
                    grad_width = render_w // 2 if pair_mode else render_w
                    grad_x = x if pair_mode else render_center_x
                    grad_y = render_center_y - render_h // 2 + band_height // 2
                    gradient_specs.append((grad_width, grad_x, grad_y))

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
                # z increases away from camera: status (z=0.05) is closest to
                # camera, in front of text (z=0.1) and gradient (z=0.3).
                status_block.sprite.position(render_center_x, render_center_y, 0.05)
                status_block.sprite.set_alpha(0.0)
                self._text_blocks.append(status_block)

                if use_gradient:
                    gradient_specs.append((render_w, render_center_x, render_center_y))

            if use_gradient and gradient_specs:
                # Paddy's #719 feedback: build texture at full render height for
                # a smoother gradient; sprite is scaled to band_height via GPU.
                texture = self._get_gradient_texture(render_h, int(255 * 0.45), brightness)
                self._background_sprites = self._adjust_gradient_sprites(
                    texture, gradient_specs, band_height
                )
            else:
                self._background_sprites = []

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
