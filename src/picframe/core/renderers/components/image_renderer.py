"""
Image Renderer Component.

Responsible for rendering images, managing textures, and executing Ken Burns transitions using pi3d.
"""
import logging
import time
from pathlib import Path
from typing import Any

import pi3d
from PIL import Image

from picframe.core.events.dto import RenderCommand, RendererConfig
from picframe.core.renderers.components.image_preparer import ImagePreparer


class ImageRenderer:
    """Renders images and handles transitions on the pi3d display."""

    def __init__(
        self,
        display: Any,
        shader: Any,
        config: RendererConfig,
        render_rect: tuple[int, int, int, int] | None = None,
    ) -> None:
        self._logger = logging.getLogger(__name__)
        self._display = display
        self._shader = shader
        self._render_rect = render_rect
        self._render_width, self._render_height = self._resolve_render_size()
        self.update_config(config)
        
        # State
        self._slide: Any | None = None
        self._sfg: Any | None = None
        self._sbg: Any | None = None
        self._video_reveal_texture: Any | None = None
        self._video_reveal_scale: tuple[float, float, float, float] | None = None
        
        self._alpha = 1.0
        self._delta_alpha = 1.0
        self._xstep = 0.0
        self._ystep = 0.0
        self._next_tm = 0.0
        
        self._init_slide()

    @staticmethod
    def _config_value(config: Any, key: str, default: Any) -> Any:
        if isinstance(config, dict):
            return config.get(key, default)
        return getattr(config, key, default)

    def update_config(self, config: RendererConfig | dict[str, Any]) -> None:
        """Refresh image-rendering settings after a runtime config change."""
        self._config = config

        blend_type_str = str(self._config_value(config, "blend_type", "blend"))
        self._blend_type = {"blend": 0.0, "burn": 1.0, "bump": 2.0}.get(blend_type_str, 0.0)
        self._edge_alpha = float(self._config_value(config, "edge_alpha", 0.5))
        self._fit = bool(self._config_value(config, "fit", False))
        self._kenburns = bool(self._config_value(config, "kenburns", False))
        if self._kenburns:
            self._fit = False

        self._fade_time = float(self._config_value(config, "time_fade", 2.0))
        self._time_delay = float(self._config_value(config, "time_delay", 200.0))
        self._fps = int(self._config_value(config, "fps", 20))
        if hasattr(self, "_image_preparer"):
            self._image_preparer.update_config(config)
        else:
            self._image_preparer = ImagePreparer(
                (self._render_width, self._render_height),
                config,
                self._create_portrait_pair_image,
                logger=self._logger,
            )

        if getattr(self, "_slide", None):
            self._slide.unif[47] = self._edge_alpha
            self._slide.unif[54] = float(self._blend_type)
            self._apply_texture_scale()

    def _init_slide(self) -> None:
        """Initialize the pi3d Sprite for the slide."""
        import pi3d
        try:
            camera = pi3d.Camera.instance()
        except AttributeError:
            # Fallback for testing when Display.INSTANCE is not fully mocked
            camera = pi3d.Camera(is_3d=False)
            
        if camera is None:
            camera = pi3d.Camera(is_3d=False)
            
        self._slide = pi3d.Sprite(
            camera=camera,
            w=self._render_width,
            h=self._render_height,
            z=5.0
        )
        self._slide.set_shader(self._shader)
        self._slide.unif[47] = self._edge_alpha
        self._slide.unif[54] = float(self._blend_type)
        self._slide.unif[55] = 1.0  # brightness
        self._position_slide()

    def _resolve_render_size(self) -> tuple[int, int]:
        if self._render_rect is not None:
            _, _, width, height = self._render_rect
            if width > 0 and height > 0:
                return int(width), int(height)
        return int(self._display.width), int(self._display.height)

    def _render_center(self) -> tuple[float, float]:
        if self._render_rect is None:
            return 0.0, 0.0
        x, y, width, height = self._render_rect
        center_x = -int(self._display.width) / 2 + x + width / 2
        center_y = int(self._display.height) / 2 - y - height / 2
        return center_x, center_y

    def _position_slide(self) -> None:
        if not self._slide or self._render_rect is None:
            return
        center_x, center_y = self._render_center()
        self._slide.position(center_x, center_y, 5.0)

    def execute(self, command: RenderCommand) -> tuple[bool, float, float]:
        """
        Load a new image and initiate a transition.
        Returns (success, kb_xstep, kb_ystep).
        """
        if self._slide is None:
            self._logger.warning("ImageRenderer not initialized properly")
            return False, 0.0, 0.0
            
        # Check if it's a video file based on extension
        ext = Path(command.image_path).suffix.lower()
        video_extensions = getattr(self._config, "video_extensions", [".mp4", ".mov", ".avi", ".mkv"])
        # Ensure extensions start with a dot
        video_extensions = [ext if ext.startswith(".") else f".{ext}" for ext in video_extensions]
        
        if ext in video_extensions:
            return False, 0.0, 0.0

        self.clear_video_reveal_texture()
        im = self._load_command_image(command)
            
        try:
            new_sfg = pi3d.Texture(im, blend=True, m_repeat=True, free_after_load=True)
            
            tm = time.time()
            self._next_tm = tm + self._time_delay
            
            self._sbg = self._sfg
            self._sfg = new_sfg
            
            if self._sbg is None:
                self._sbg = self._sfg
                
            self._slide.set_textures([self._sfg, self._sbg])
            
            self._copy_front_scale_to_back()
            
            xstep, ystep = self._apply_texture_scale()
                
            return True, xstep, ystep
                
        except Exception as e:
            self._logger.error(f"Failed to execute RenderCommand in ImageRenderer: {e}")
            return False, 0.0, 0.0

    def preload_video_reveal_texture(self, command: RenderCommand) -> bool:
        """Preload a video last-frame texture without changing active slide textures."""
        if self._slide is None:
            self._logger.warning("ImageRenderer not initialized properly")
            return False

        try:
            im = self._load_command_image(command)
            texture = pi3d.Texture(im, blend=True, m_repeat=True, free_after_load=True)
        except Exception as e:
            self._logger.error(f"Failed to preload video reveal texture {command.image_path}: {e}")
            return False

        self._video_reveal_texture = texture
        self._video_reveal_scale = self._texture_scale_values(texture)
        return True

    def promote_video_reveal_texture(self) -> bool:
        """Make the preloaded video reveal texture the visible foreground texture."""
        if self._slide is None or self._video_reveal_texture is None:
            return False

        reveal_texture = self._video_reveal_texture
        reveal_scale = self._video_reveal_scale or self._texture_scale_values(reveal_texture)
        previous_front = self._sfg

        self._sfg = reveal_texture
        if previous_front is not None:
            self._sbg = previous_front
            self._copy_front_scale_to_back()
        elif self._sbg is None:
            self._sbg = reveal_texture

        self._slide.set_textures([self._sfg, self._sbg])
        self._apply_front_scale_values(reveal_scale)
        self.set_alpha(1.0)
        self._video_reveal_texture = None
        self._video_reveal_scale = None
        return True

    def clear_video_reveal_texture(self) -> None:
        """Drop any preloaded video reveal texture that no longer applies."""
        self._video_reveal_texture = None
        self._video_reveal_scale = None

    def _load_command_image(self, command: RenderCommand) -> Image.Image:
        try:
            if command.layout == "portrait_pair":
                return self._load_portrait_pair(command)
            if getattr(command, "image_obj", None) is not None:
                return self._image_preparer.prepare_unmatted_image(command.image_obj)
            return self._image_preparer.load_single_image(command.image_path)
        except Exception as e:
            self._logger.error(f"Failed to load image {command.image_path}: {e}")
            from picframe.core.exceptions import MediaProcessingError
            raise MediaProcessingError(f"Failed to load image {command.image_path}: {e}") from e

    def _copy_front_scale_to_back(self) -> None:
        if not self._slide:
            return
        self._slide.unif[45:47] = self._slide.unif[42:44]
        self._slide.unif[51:53] = self._slide.unif[48:50]

    def _texture_scale_values(self, texture: Any) -> tuple[float, float, float, float]:
        wh_rat = (self._render_width * texture.iy) / (self._render_height * texture.ix)
        if (wh_rat > 1.0 and self._fit) or (wh_rat <= 1.0 and not self._fit):
            return wh_rat, 1.0, (wh_rat - 1.0) * 0.5, 0.0

        wh_rat = 1.0 / wh_rat
        return 1.0, wh_rat, 0.0, (wh_rat - 1.0) * 0.5

    def _apply_front_scale_values(self, values: tuple[float, float, float, float]) -> None:
        if not self._slide:
            return
        scale_x, scale_y, offset_x, offset_y = values
        self._slide.unif[42] = scale_x
        self._slide.unif[43] = scale_y
        self._slide.unif[48] = offset_x
        self._slide.unif[49] = offset_y

    def _apply_texture_scale(self) -> tuple[float, float]:
        """Apply fit/crop shader uniforms for the current front texture."""
        if not self._slide or not self._sfg:
            return 0.0, 0.0

        self._apply_front_scale_values(self._texture_scale_values(self._sfg))

        if not self._kenburns:
            return 0.0, 0.0

        xstep = self._slide.unif[48] * 2.0 / (self._time_delay - self._fade_time)
        ystep = self._slide.unif[49] * 2.0 / (self._time_delay - self._fade_time)
        self._slide.unif[48] = 0.0
        self._slide.unif[49] = 0.0
        return xstep, ystep

    def _load_portrait_pair(self, command: RenderCommand) -> Image.Image:
        """Load and combine a two-image portrait pair in memory."""
        return self._image_preparer.load_portrait_pair(command)

    @staticmethod
    def _create_portrait_pair_image(im1: Image.Image, im2: Image.Image) -> Image.Image:
        """Concatenate two portrait images horizontally using legacy sizing rules."""
        sep = 8
        if im1.mode != "RGB":
            im1 = im1.convert("RGB")
        if im2.mode != "RGB":
            im2 = im2.convert("RGB")

        if im1.width > im2.width:
            im1 = im1.resize(
                (im2.width, int(im1.height * im2.width / im1.width)),
                resample=Image.Resampling.BICUBIC,
            )
        elif im2.width > im1.width:
            im2 = im2.resize(
                (im1.width, int(im2.height * im1.width / im2.width)),
                resample=Image.Resampling.BICUBIC,
            )

        dst = Image.new("RGB", (im1.width + im2.width + sep, min(im1.height, im2.height)))
        dst.paste(im1, (0, 0))
        dst.paste(im2, (im1.width + sep, 0))
        return dst

    def set_alpha(self, alpha: float) -> None:
        """Set the alpha value for the transition."""
        if self._slide:
            # Smooth step alpha
            self._slide.unif[44] = alpha * alpha * (3.0 - 2.0 * alpha)

    def set_kenburns_offsets(self, x: float, y: float) -> None:
        """Set the Ken Burns tweening offsets."""
        if self._slide:
            self._slide.unif[48] = x
            self._slide.unif[49] = y

    def draw(self) -> None:
        """Draw the image slide."""
        if self._slide:
            self._slide.draw()
