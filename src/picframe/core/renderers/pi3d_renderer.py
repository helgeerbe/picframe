"""
Pi3d implementation of the IRenderer interface.
"""
import logging
import time
from typing import Any

import pi3d
from PIL import Image

from picframe.core.events.dto import RenderCommand
from picframe.core.renderers.interfaces import IRenderer


class Pi3dRenderer(IRenderer):
    """
    Renderer implementation using the pi3d library.
    
    Responsible for managing the OpenGL/EGL context, loading textures,
    and executing image transitions (alpha blending, Ken Burns).
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """
        Initialize the renderer with configuration.
        
        Args:
            config: Dictionary containing display and rendering settings.
        """
        self._logger = logging.getLogger(__name__)
        self._config = config
        
        # Display settings
        self._display_x = int(config.get("display_x", 0))
        self._display_y = int(config.get("display_y", 0))
        self._display_w = config.get("display_w")
        if self._display_w is not None:
            self._display_w = int(self._display_w)
        self._display_h = config.get("display_h")
        if self._display_h is not None:
            self._display_h = int(self._display_h)
            
        self._fps = int(config.get("fps", 20))
        self._background = config.get("background", (0.0, 0.0, 0.0, 1.0))
        self._use_glx = bool(config.get("use_glx", False))
        self._use_sdl2 = bool(config.get("use_sdl2", False))
        
        # Rendering settings
        self._shader_path = config.get("shader", "blend_new")
        blend_type_str = config.get("blend_type", "blend")
        self._blend_type = {"blend": 0.0, "burn": 1.0, "bump": 2.0}.get(blend_type_str, 0.0)
        self._edge_alpha = float(config.get("edge_alpha", 0.5))
        self._fit = bool(config.get("fit", False))
        self._kenburns = bool(config.get("kenburns", False))
        if self._kenburns:
            self._fit = False
            
        self._fade_time = float(config.get("time_fade", 2.0))
        self._time_delay = float(config.get("time_delay", 200.0))
        
        # State
        self._display: pi3d.Display | None = None
        self._slide: pi3d.Sprite | None = None
        self._sfg: pi3d.Texture | None = None
        self._sbg: pi3d.Texture | None = None
        
        self._alpha = 1.0
        self._delta_alpha = 1.0
        self._xstep = 0.0
        self._ystep = 0.0
        self._next_tm = 0.0

    def start(self) -> None:
        """Initialize the pi3d display and sprite."""
        self._logger.info("Starting Pi3dRenderer")
        self._display = pi3d.Display.create(
            x=self._display_x,
            y=self._display_y,
            w=self._display_w,
            h=self._display_h,
            frames_per_second=self._fps,
            display_config=pi3d.DISPLAY_CONFIG_HIDE_CURSOR | pi3d.DISPLAY_CONFIG_NO_FRAME,
            background=self._background,
            use_glx=self._use_glx,
            use_sdl2=self._use_sdl2,
        )
        
        camera = pi3d.Camera(is_3d=False)
        shader = pi3d.Shader(self._shader_path)
        
        self._slide = pi3d.Sprite(
            camera=camera,
            w=self._display.width,
            h=self._display.height,
            z=5.0
        )
        self._slide.set_shader(shader)
        self._slide.unif[47] = self._edge_alpha
        self._slide.unif[54] = float(self._blend_type)
        self._slide.unif[55] = 1.0  # brightness

    def stop(self) -> None:
        """Destroy the pi3d display."""
        self._logger.info("Stopping Pi3dRenderer")
        if self._display is not None:
            self._display.destroy()
            self._display = None

    def execute(self, command: RenderCommand) -> None:
        """
        Load a new image and initiate a transition.
        """
        if self._display is None or self._slide is None:
            self._logger.warning("Renderer not started, ignoring command")
            return
            
        try:
            # Load texture
            # In a real implementation, ImageProcessingService would have already
            # matted/resized the image and saved it to a cache path, or we load it directly.
            # For now, we load the image path directly.
            im = Image.open(command.image_path)
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
            
            # Calculate aspect ratio adjustments
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
            
            if self._kenburns:
                self._xstep = self._slide.unif[48] * 2.0 / (self._time_delay - self._fade_time)
                self._ystep = self._slide.unif[49] * 2.0 / (self._time_delay - self._fade_time)
                self._slide.unif[48] = 0.0
                self._slide.unif[49] = 0.0
                
            # Start transition
            self._alpha = 0.0
            if self._fade_time > 0.5:
                self._delta_alpha = 1.0 / (self._fps * self._fade_time)
            else:
                self._delta_alpha = 1.0
                
        except Exception as e:
            self._logger.error(f"Failed to execute RenderCommand: {e}")

    def render_frame(self) -> bool:
        """
        Draw the current frame and update transition state.
        """
        if self._display is None or self._slide is None:
            return False
            
        loop_running = self._display.loop_running()
        if not loop_running:
            return False
            
        tm = time.time()
        
        # Update Ken Burns tweening
        if self._kenburns and self._alpha >= 1.0:
            t_factor = self._time_delay - self._fade_time - self._next_tm + tm
            self._slide.unif[48] = self._slide.unif[48] * 0.95 + self._xstep * t_factor * 0.05
            self._slide.unif[49] = self._slide.unif[49] * 0.95 + self._ystep * t_factor * 0.05
            
        # Update alpha transition
        if self._alpha < 1.0:
            self._alpha += self._delta_alpha
            if self._alpha > 1.0:
                self._alpha = 1.0
            # Smooth step alpha
            self._slide.unif[44] = self._alpha * self._alpha * (3.0 - 2.0 * self._alpha)
            
        self._slide.draw()
        
        return True
