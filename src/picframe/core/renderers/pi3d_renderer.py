"""
Pi3d implementation of the IRenderer interface.
"""
import logging
import time
from typing import Any

import pi3d
from PIL import Image

from enum import Enum, auto
from picframe.core.events.dto import RenderCommand, StateEvent, State, OverlayConfig
from picframe.core.renderers.interfaces import IRenderer
from picframe.core.events.interfaces import IEventSubscriber
from picframe.core.renderers.components.text_renderer import TextRenderer
from picframe.core.renderers.components.clock_renderer import ClockRenderer
from picframe.core.repositories.interfaces import IConfigRepository

class RenderState(Enum):
    STATIC = auto()
    IMAGE_TRANSITIONING = auto()
    TEXT_FADING_IN = auto()
    TEXT_SHOWING = auto()
    TEXT_FADING_OUT = auto()


class Pi3dRenderer(IRenderer):
    """
    Renderer implementation using the pi3d library.
    
    Responsible for managing the OpenGL/EGL context, loading textures,
    and executing image transitions (alpha blending, Ken Burns).
    """

    def __init__(self, config: dict[str, Any], event_subscriber: IEventSubscriber | None = None, config_repository: IConfigRepository | None = None) -> None:
        """
        Initialize the renderer with configuration.
        
        Args:
            config: Dictionary containing display and rendering settings.
            event_subscriber: Optional event subscriber to listen for config changes.
            config_repository: Optional repository to fetch live configuration updates.
        """
        self._logger = logging.getLogger(__name__)
        self._config = config
        self._event_subscriber = event_subscriber
        self._config_repository = config_repository
        
        if self._event_subscriber:
            self._event_subscriber.subscribe(StateEvent, self._handle_state_event)
        
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
        self._display: Any | None = None
        self._slide: Any | None = None
        self._sfg: Any | None = None
        self._sbg: Any | None = None
        
        self._alpha = 1.0
        self._delta_alpha = 1.0
        self._xstep = 0.0
        self._ystep = 0.0
        self._next_tm = 0.0
        
        # Text Overlay State
        if self._config_repository:
            self._overlay_config = OverlayConfig(
                show_clock=bool(self._config_repository.get_app_config("viewer.show_clock", config.get("show_clock", False))),
                clock_format=str(self._config_repository.get_app_config("viewer.clock_format", config.get("clock_format", "%H:%M"))),
                show_text=bool(self._config_repository.get_app_config("viewer.show_text", config.get("show_text", False))),
                text_string=str(self._config_repository.get_app_config("viewer.text_string", config.get("text_string", "")))
            )
        else:
            self._overlay_config = OverlayConfig(
                show_clock=bool(config.get("show_clock", False)),
                clock_format=str(config.get("clock_format", "%H:%M")),
                show_text=bool(config.get("show_text", False)),
                text_string=str(config.get("text_string", ""))
            )
        self._text_renderer: TextRenderer | None = None
        self._clock_renderer: ClockRenderer | None = None
        self._render_state = RenderState.STATIC
        self._text_alpha = 0.0
        self._text_fade_time = 1.0
        self._text_show_time = float(config.get("show_text_tm", 10.0))
        self._text_timer = 0.0

    def _handle_state_event(self, event: Any) -> None:
        if not isinstance(event, StateEvent):
            return
            
        if event.state == State.CONFIG_CHANGED:
            payload = event.payload or {}
            updated_sections = payload.get("updated_sections", [])
            
            if "viewer" in updated_sections or "text_overlay" in updated_sections:
                self._logger.info("Renderer received CONFIG_CHANGED for viewer/overlay section. Updating overlay state.")
                if self._config_repository:
                    self._overlay_config = OverlayConfig(
                        show_clock=bool(self._config_repository.get_app_config("viewer.show_clock", self._overlay_config.show_clock)),
                        clock_format=str(self._config_repository.get_app_config("viewer.clock_format", self._overlay_config.clock_format)),
                        show_text=bool(self._config_repository.get_app_config("viewer.show_text", self._overlay_config.show_text)),
                        text_string=str(self._config_repository.get_app_config("viewer.text_string", self._overlay_config.text_string))
                    )
                    if self._text_renderer:
                        self._text_renderer.update_config(self._overlay_config)
                    if self._clock_renderer:
                        self._clock_renderer.update_config(self._overlay_config)

    def start(self) -> None:
        """Initialize the pi3d display and sprite."""
        self._logger.info("Starting Pi3dRenderer")
        self._logger.debug("Calling pi3d.Display.create...")
        try:
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
            self._logger.debug("pi3d.Display.create returned successfully.")
        except Exception as e:
            self._logger.error(f"Failed to create pi3d display: {e}", exc_info=True)
            raise
        
        camera = pi3d.Camera(is_3d=False)
        shader = pi3d.Shader(self._shader_path)
        flat_shader = pi3d.Shader("uv_flat")
        
        self._text_renderer = TextRenderer(self._display, flat_shader, self._config.get("font_file", ""))
        self._clock_renderer = ClockRenderer(self._display, flat_shader, self._config.get("font_file", ""))
        
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
            
        if command.overlay:
            self._overlay_config = command.overlay
            
        try:
            # Load texture
            # In a real implementation, ImageProcessingService would have already
            # matted/resized the image and saved it to a cache path, or we load it directly.
            # For now, we load the image path directly.
            try:
                im = Image.open(command.image_path)
            except Exception as e:
                self._logger.warning(f"Failed to load image {command.image_path}: {e}. Using fallback.")
                # Create a fallback image (e.g., black screen or default "no pictures" image)
                im = Image.new('RGB', (self._display.width, self._display.height), color='black')
                
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
                
            self._render_state = RenderState.IMAGE_TRANSITIONING
            
            if self._text_renderer:
                self._text_renderer.update_config(self._overlay_config)
            if self._clock_renderer:
                self._clock_renderer.update_config(self._overlay_config)
                
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
        
        # Ensure camera is set for the display
        import pi3d
        if pi3d.Camera.instance() is None:
            pi3d.Camera(is_3d=False)
        
        # Update Ken Burns tweening
        if self._kenburns and self._alpha >= 1.0:
            t_factor = self._time_delay - self._fade_time - self._next_tm + tm
            self._slide.unif[48] = self._slide.unif[48] * 0.95 + self._xstep * t_factor * 0.05
            self._slide.unif[49] = self._slide.unif[49] * 0.95 + self._ystep * t_factor * 0.05
            
        # State Machine
        if self._render_state == RenderState.IMAGE_TRANSITIONING:
            if self._alpha < 1.0:
                self._alpha += self._delta_alpha
                if self._alpha >= 1.0:
                    self._alpha = 1.0
                    if self._overlay_config.show_text:
                        self._render_state = RenderState.TEXT_FADING_IN
                        self._text_alpha = 0.0
                    else:
                        self._render_state = RenderState.STATIC
                # Smooth step alpha
                self._slide.unif[44] = self._alpha * self._alpha * (3.0 - 2.0 * self._alpha)
                
        elif self._render_state == RenderState.TEXT_FADING_IN:
            self._text_alpha += 1.0 / (self._fps * self._text_fade_time)
            if self._text_alpha >= 1.0:
                self._text_alpha = 1.0
                self._render_state = RenderState.TEXT_SHOWING
                self._text_timer = tm + self._text_show_time
            if self._text_renderer:
                self._text_renderer.set_alpha(self._text_alpha)
                
        elif self._render_state == RenderState.TEXT_SHOWING:
            if tm >= self._text_timer:
                self._render_state = RenderState.TEXT_FADING_OUT
                
        elif self._render_state == RenderState.TEXT_FADING_OUT:
            self._text_alpha -= 1.0 / (self._fps * self._text_fade_time)
            if self._text_alpha <= 0.0:
                self._text_alpha = 0.0
                self._render_state = RenderState.STATIC
            if self._text_renderer:
                self._text_renderer.set_alpha(self._text_alpha)
                
        self._slide.draw()
        
        if self._text_renderer and self._render_state in (RenderState.TEXT_FADING_IN, RenderState.TEXT_SHOWING, RenderState.TEXT_FADING_OUT):
            self._text_renderer.draw()
            
        if self._clock_renderer:
            self._clock_renderer.draw()
        
        return True
