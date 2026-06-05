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

    def __init__(self, display: Any, shader: Any, config: RendererConfig) -> None:
        self._logger = logging.getLogger(__name__)
        self._display = display
        self._shader = shader
        self.update_config(config)
        
        # State
        self._slide: Any | None = None
        self._sfg: Any | None = None
        self._sbg: Any | None = None
        
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
                (self._display.width, self._display.height),
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
            w=self._display.width,
            h=self._display.height,
            z=5.0
        )
        self._slide.set_shader(self._shader)
        self._slide.unif[47] = self._edge_alpha
        self._slide.unif[54] = float(self._blend_type)
        self._slide.unif[55] = 1.0  # brightness

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

        try:
            if command.layout == "portrait_pair":
                im = self._load_portrait_pair(command)
            elif getattr(command, "image_obj", None) is not None:
                im = self._image_preparer.prepare_unmatted_image(command.image_obj)
            else:
                im = self._image_preparer.load_single_image(command.image_path)
        except Exception as e:
            self._logger.error(f"Failed to load image {command.image_path}: {e}")
            from picframe.core.exceptions import MediaProcessingError
            raise MediaProcessingError(f"Failed to load image {command.image_path}: {e}") from e
            
        try:
            new_sfg = pi3d.Texture(im, blend=True, m_repeat=True, free_after_load=True)
            
            tm = time.time()
            self._next_tm = tm + self._time_delay
            
            self._sbg = self._sfg
            self._sfg = new_sfg
            
            if self._sbg is None:
                self._sbg = self._sfg
                
            self._slide.set_textures([self._sfg, self._sbg])
            
            # Transfer front width/height factors to back
            self._slide.unif[45:47] = self._slide.unif[42:44]
            # Transfer front width/height offsets to back
            self._slide.unif[51:53] = self._slide.unif[48:50]
            
            xstep, ystep = self._apply_texture_scale()
                
            return True, xstep, ystep
                
        except Exception as e:
            self._logger.error(f"Failed to execute RenderCommand in ImageRenderer: {e}")
            return False, 0.0, 0.0

    def _apply_texture_scale(self) -> tuple[float, float]:
        """Apply fit/crop shader uniforms for the current front texture."""
        if not self._slide or not self._sfg:
            return 0.0, 0.0

        wh_rat = (self._display.width * self._sfg.iy) / (self._display.height * self._sfg.ix)
        if (wh_rat > 1.0 and self._fit) or (wh_rat <= 1.0 and not self._fit):
            sz1, sz2, os1, os2 = 42, 43, 48, 49
        else:
            sz1, sz2, os1, os2 = 43, 42, 49, 48
            wh_rat = 1.0 / wh_rat

        self._slide.unif[sz1] = wh_rat
        self._slide.unif[sz2] = 1.0
        self._slide.unif[os1] = (wh_rat - 1.0) * 0.5
        self._slide.unif[os2] = 0.0

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
