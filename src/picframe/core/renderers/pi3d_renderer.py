"""
Pi3d implementation of the IRenderer interface.
"""
import logging
import os
import queue
import time
from dataclasses import dataclass, field, replace
from typing import Any

import pi3d

from picframe.core.events.dto import (
    CurrentMediaChangedEvent,
    OverlayConfig,
    RenderCommand,
    RendererConfig,
    RendererConfigUpdatedEvent,
    State,
    StateEvent,
)
from picframe.core.events.interfaces import IEventSubscriber
from picframe.core.renderers.animation_controller import AnimationController, RenderState
from picframe.core.renderers.components.clock_renderer import ClockRenderer
from picframe.core.renderers.components.image_renderer import ImageRenderer
from picframe.core.renderers.components.text_renderer import TextRenderer
from picframe.core.renderers.interfaces import IRenderer
from picframe.core.repositories.interfaces import IConfigRepository


@dataclass(order=True)
class PrioritizedRenderTask:
    priority: int
    task: Any = field(compare=False)


class Pi3dRenderer(IRenderer):
    """
    Renderer implementation using the pi3d library.
    
    Responsible for managing the OpenGL/EGL context, loading textures,
    and executing image transitions (alpha blending, Ken Burns).
    """

    @staticmethod
    def _parse_bool_config(raw_value: Any) -> bool:
        """
        Parse a boolean configuration value from various string representations.
        """
        if isinstance(raw_value, bool):
            return raw_value
        val_str = str(raw_value).strip().lower()
        return val_str in ("true", "1", "t", "y", "yes", "on")

    @staticmethod
    def _parse_show_text_config(raw_value: Any) -> bool:
        """
        Parse the overloaded show_text configuration.
        It can be a boolean toggle or a format string.
        Returns False only if explicitly set to a falsy string/value.
        """
        if isinstance(raw_value, bool):
            return raw_value
        val_str = str(raw_value).strip().lower()
        if val_str in ("false", "off", "0", "none", "no", ""):
            return False
        return True

    def __init__(
        self,
        config: RendererConfig,
        event_subscriber: IEventSubscriber | None = None,
    ) -> None:
        """
        Initialize the renderer with configuration.
        
        Args:
            config: Strongly-typed configuration for the renderer.
            event_subscriber: Optional event subscriber to listen for config changes.
        """
        self._logger = logging.getLogger(__name__)
        self._config = config
        self._event_subscriber = event_subscriber
        
        if self._event_subscriber:
            self._event_subscriber.subscribe(RendererConfigUpdatedEvent, self._handle_config_event)
            self._event_subscriber.subscribe(CurrentMediaChangedEvent, self._handle_state_event)
        
        # Display settings
        self._display_x = config.display_x
        self._display_y = config.display_y
        self._display_w = config.display_w
        self._display_h = config.display_h
            
        self._fps = config.fps
        self._background = config.background
        self._use_glx = config.use_glx
        self._use_sdl2 = config.use_sdl2
        
        # Rendering settings
        self._shader_path = os.path.expanduser(config.shader_path)
        self._kenburns = config.kenburns
        
        # State
        self._display: Any | None = None
        self._image_renderer: ImageRenderer | None = None
        
        # Text Overlay State
        self._overlay_config = OverlayConfig(
            show_clock=config.show_clock,
            clock_format=config.clock_format,
            show_text=config.show_text_enabled,
            text_string=""
        )
        self._text_renderer: TextRenderer | None = None
        self._clock_renderer: ClockRenderer | None = None
        
        # Convert RendererConfig to dict for AnimationController compatibility
        anim_config = {
            "fps": config.fps,
            "time_fade": config.time_fade,
            "time_delay": config.time_delay,
            "show_text_tm": config.show_text_tm,
            "kenburns": config.kenburns
        }
        self._animation_controller = AnimationController(anim_config)
        self._animation_controller.update_text_config(self._overlay_config.show_text, False)
        
        self._local_queue: queue.PriorityQueue[PrioritizedRenderTask] = queue.PriorityQueue()
        self._current_media: Any | None = None

    def _generate_text_string(self, media_item: Any) -> str:
        """Generate the text overlay string based on configuration and media metadata."""
        if not media_item or getattr(media_item, "filepath", "").endswith("no_pictures.jpg"):
            return ""
            
        if not self._config.show_text_enabled:
            return ""
            
        show_text_config = self._config.text_overlay_format.lower()
        show_text_fm = "%b %d, %Y" # Default, could be added to RendererConfig if needed
            
        parts = []
        if "title" in show_text_config and getattr(media_item, "title", None):
            parts.append(media_item.title)
        if "caption" in show_text_config and getattr(media_item, "caption", None):
            parts.append(media_item.caption)
        if "name" in show_text_config and getattr(media_item, "filename", None):
            parts.append(media_item.filename)
        if "date" in show_text_config and getattr(media_item, "exif_datetime", None):
            import datetime
            try:
                dt = datetime.datetime.fromtimestamp(media_item.exif_datetime)
                parts.append(dt.strftime(show_text_fm))
            except Exception:
                pass
        if "folder" in show_text_config and getattr(media_item, "filepath", None):
            parts.append(os.path.basename(os.path.dirname(media_item.filepath)))
        if "location" in show_text_config and getattr(media_item, "location", None):
            parts.append(media_item.location)
            
        return " - ".join(parts)

    def _handle_config_event(self, event: Any) -> None:
        if not isinstance(event, RendererConfigUpdatedEvent):
            return
            
        self._logger.info("Renderer received RendererConfigUpdatedEvent. Updating state.")
        self._config = event.config
        
        old_text_string = self._overlay_config.text_string
        new_text_string = old_text_string
        
        if self._current_media:
            new_text_string = self._generate_text_string(self._current_media)
            
        self._overlay_config = OverlayConfig(
            show_clock=self._config.show_clock,
            clock_format=self._config.clock_format,
            show_text=self._config.show_text_enabled,
            text_string=new_text_string,
        )
        
        if self._text_renderer:
            self._text_renderer.update_config(self._overlay_config)
        if self._clock_renderer:
            self._clock_renderer.update_config(self._overlay_config)
            
        self._animation_controller.force_redraw(2)
        self._animation_controller.update_text_config(
            self._overlay_config.show_text,
            self._overlay_config.text_string != old_text_string
        )

    def _handle_state_event(self, event: Any) -> None:
        if isinstance(event, CurrentMediaChangedEvent):
            self._current_media = event.media_item
            
            # Update text string when media changes
            if self._config.show_text_enabled:
                new_text_string = self._generate_text_string(self._current_media)
                if new_text_string != self._overlay_config.text_string:
                    self._overlay_config = replace(self._overlay_config, text_string=new_text_string)
                    if self._text_renderer:
                        self._text_renderer.update_config(self._overlay_config)
                    self._animation_controller.force_redraw(2)
                    self._animation_controller.update_text_config(True, True)

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
        
        pi3d.Camera(is_3d=False)
        shader = pi3d.Shader(self._shader_path)
        flat_shader = pi3d.Shader("uv_flat")
        
        self._image_renderer = ImageRenderer(self._display, shader, self._config)
        
        font_file = os.path.expanduser(self._config.font_file)
        self._text_renderer = TextRenderer(self._display, flat_shader, font_file)
        self._clock_renderer = ClockRenderer(self._display, flat_shader, font_file)

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
        if self._display is None or self._image_renderer is None:
            self._logger.warning("Renderer not started, ignoring command")
            return
            
        if command.overlay:
            self._overlay_config = replace(
                self._overlay_config, text_string=command.overlay.text_string
            )
            
        try:
            if command.image_path == "SUSPEND":
                self._animation_controller.suspend()
                return
            elif command.image_path == "RESUME":
                self._animation_controller.resume()
                return

            # Delegate to ImageRenderer
            success, kb_xstep, kb_ystep = self._image_renderer.execute(command)
            if success:
                self._animation_controller.start_transition(time.time(), kb_xstep, kb_ystep)
                self._animation_controller.update_text_config(self._overlay_config.show_text, True)
                
                if self._text_renderer:
                    self._text_renderer.update_config(self._overlay_config)
                if self._clock_renderer:
                    self._clock_renderer.update_config(self._overlay_config)
                
        except Exception as e:
            self._logger.error(f"Failed to execute RenderCommand: {e}")

    def enqueue_task(self, priority: int, task: Any) -> None:
        """Enqueue a high-frequency task (like a clock tick) for the render loop."""
        self._local_queue.put(PrioritizedRenderTask(priority=priority, task=task))

    def render_frame(self) -> bool:
        """
        Draw the current frame and update transition state.
        """
        if self._display is None or self._image_renderer is None:
            return False
            
        tm = time.time()
        anim_state = self._animation_controller.update(tm)

        # Process local queue
        try:
            while True:
                task_item = self._local_queue.get_nowait()
                if task_item.task == "clock_tick":
                    if anim_state.render_state == RenderState.STATIC:
                        self._animation_controller.force_redraw(2)
                self._local_queue.task_done()
        except queue.Empty:
            pass

        # Sleep optimization for SUSPENDED state
        if anim_state.render_state == RenderState.SUSPENDED:
            time.sleep(0.1)
            return True

        needs_redraw = False
        
        # 1. Check animation and transition states
        if (anim_state.render_state in (RenderState.TRANSITIONING, RenderState.TEXT_ANIMATING) or
            self._kenburns or
            anim_state.frames_to_render > 0 or
            anim_state.text_alpha != getattr(self, '_last_text_alpha', -1.0)):
            needs_redraw = True
            
        # 2. Check dynamic overlays (Clock)
        elif self._clock_renderer:
            if self._clock_renderer.has_changed():
                needs_redraw = True
                
        # 3. OS Keepalive (prevent Wayland/X11 "Not Responding" hangs)
        elif (tm - getattr(self, '_last_redraw_time', 0)) > 10.0:
            needs_redraw = True

        # --- STATIC BYPASS ---
        if not needs_redraw:
            time.sleep(0.05) # Yield CPU to OS
            return True      # Keep PlaybackEngine loop alive

        # --- ACTIVE RENDER BLOCK ---
        loop_running = self._display.loop_running()
        if not loop_running:
            return False

        self._last_redraw_time = tm
        self._last_text_alpha = anim_state.text_alpha

        # Apply animation state to components
        self._image_renderer.set_alpha(anim_state.image_alpha)
        if self._kenburns:
            self._image_renderer.set_kenburns_offsets(anim_state.kenburns_x, anim_state.kenburns_y)
            
        if self._text_renderer:
            self._text_renderer.set_alpha(anim_state.text_alpha)

        # Draw components
        self._image_renderer.draw()
        
        if self._text_renderer and self._overlay_config.show_text:
            self._text_renderer.draw()
            
        if self._clock_renderer and self._overlay_config.show_clock:
            self._clock_renderer.draw()

        return True
