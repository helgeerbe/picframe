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

    def __init__(
        self,
        config: dict[str, Any],
        event_subscriber: IEventSubscriber | None = None,
        config_repository: IConfigRepository | None = None,
    ) -> None:
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
            self._event_subscriber.subscribe(CurrentMediaChangedEvent, self._handle_state_event)
        
        # Display settings
        self._display_x = int(config.get("display_x", 0))
        self._display_y = int(config.get("display_y", 0))
        self._display_w = config.get("display_w")
        if self._display_w is not None and self._display_w != "":
            self._display_w = int(self._display_w)
        else:
            self._display_w = None
        self._display_h = config.get("display_h")
        if self._display_h is not None and self._display_h != "":
            self._display_h = int(self._display_h)
        else:
            self._display_h = None
            
        self._fps = int(config.get("fps", 20))
        self._background = config.get("background", (0.0, 0.0, 0.0, 1.0))
        self._use_glx = bool(config.get("use_glx", False))
        self._use_sdl2 = bool(config.get("use_sdl2", False))
        
        # Rendering settings
        self._shader_path = os.path.expanduser(config.get("shader", "blend_new"))
        self._kenburns = bool(config.get("kenburns", False))
        
        # State
        self._display: Any | None = None
        self._image_renderer: ImageRenderer | None = None
        
        # Text Overlay State
        if self._config_repository:
            self._overlay_config = OverlayConfig(
                show_clock=bool(
                    self._config_repository.get_app_config(
                        "viewer.show_clock", config.get("show_clock", False)
                    )
                ),
                clock_format=str(
                    self._config_repository.get_app_config(
                        "viewer.clock_format", config.get("clock_format", "%H:%M")
                    )
                ),
                show_text=bool(
                    self._config_repository.get_app_config(
                        "viewer.show_text", config.get("show_text", False)
                    )
                ),
                text_string=str(
                    self._config_repository.get_app_config(
                        "viewer.text_string", config.get("text_string", "")
                    )
                ),
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
        
        self._animation_controller = AnimationController(config)
        self._animation_controller.update_text_config(self._overlay_config.show_text, False)
        
        self._local_queue: queue.PriorityQueue[PrioritizedRenderTask] = queue.PriorityQueue()
        self._current_media: Any | None = None

    def _generate_text_string(self, media_item: Any) -> str:
        """Generate the text overlay string based on configuration and media metadata."""
        if not media_item or getattr(media_item, "filepath", "").endswith("no_pictures.jpg"):
            return ""
            
        if self._config_repository:
            show_text_config = str(
                self._config_repository.get_app_config(
                    "viewer.show_text", self._config.get("show_text", "")
                )
            ).lower()
            show_text_fm = str(
                self._config_repository.get_app_config(
                    "viewer.show_text_fm", self._config.get("show_text_fm", "%b %d, %Y")
                )
            )
        else:
            show_text_config = str(self._config.get("show_text", "")).lower()
            show_text_fm = str(self._config.get("show_text_fm", "%b %d, %Y"))
            
        if not show_text_config or show_text_config == "false" or show_text_config == "off":
            return ""
            
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

    def _handle_state_event(self, event: Any) -> None:
        if isinstance(event, CurrentMediaChangedEvent):
            self._current_media = event.media_item
            return
            
        if not isinstance(event, StateEvent):
            return
            
        if event.state == State.CONFIG_CHANGED:
            payload = event.payload or {}
            updated_sections = payload.get("updated_sections", [])
            
            if "viewer" in updated_sections or "text_overlay" in updated_sections:
                self._logger.info(
                    "Renderer received CONFIG_CHANGED for viewer/overlay section. "
                    "Updating overlay state."
                )
                old_text_string = self._overlay_config.text_string
                
                if self._config_repository:
                    new_text_string = self._overlay_config.text_string
                    if self._current_media:
                        new_text_string = self._generate_text_string(self._current_media)
                        
                    self._overlay_config = OverlayConfig(
                        show_clock=bool(
                            self._config_repository.get_app_config(
                                "viewer.show_clock", self._overlay_config.show_clock
                            )
                        ),
                        clock_format=str(
                            self._config_repository.get_app_config(
                                "viewer.clock_format", self._overlay_config.clock_format
                            )
                        ),
                        show_text=bool(
                            self._config_repository.get_app_config(
                                "viewer.show_text", self._overlay_config.show_text
                            )
                        ),
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
        
        font_file = os.path.expanduser(self._config.get("font_file", ""))
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

        loop_running = self._display.loop_running()
        if not loop_running:
            return False

        # Sleep optimization for STATIC and SUSPENDED states
        if anim_state.render_state == RenderState.SUSPENDED:
            time.sleep(0.1)
            return True
            
        if (
            anim_state.render_state == RenderState.STATIC
            and not self._kenburns
            and anim_state.frames_to_render <= 0
        ):
            time.sleep(0.1)
            # Do not return early; we must draw the static frame to prevent
            # the screen from going black

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
