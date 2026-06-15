"""
Pi3d implementation of the IRenderer interface.
"""
import logging
import os
import queue
import signal
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pi3d

from picframe.core.events.dto import (
    CurrentMediaChangedEvent,
    OverlayConfig,
    RENDER_PARK_VIDEO_REVEAL,
    RENDER_PRELOAD_VIDEO_REVEAL,
    RENDER_PROMOTE_VIDEO_REVEAL,
    RENDER_WAKE_VIDEO_REVEAL,
    RenderCommand,
    RendererConfig,
    RendererConfigUpdatedEvent,
    State,
    StateEvent,
)
from picframe.core.events.interfaces import IEventPublisher, IEventSubscriber
from picframe.core.models.media import DisplayItem, DisplayLayout
from picframe.core.renderers.animation_controller import AnimationController, RenderState
from picframe.core.renderers.components.clock_renderer import ClockRenderer
from picframe.core.renderers.components.image_renderer import ImageRenderer
from picframe.core.renderers.components.text_renderer import TextRenderer
from picframe.core.renderers.interfaces import IRenderer
from picframe.core.repositories.interfaces import IConfigRepository
from picframe.core.services.overlay_text import apply_geo_suppress_list

PI3D_LABWC_IDENTIFIER = "picframe-pi3d"
VIDEO_WINDOW_TITLE = "picframe-video"
RESUME_REDRAW_FRAMES = 5
TEXT_CLEAR_REDRAW_FRAMES = 2
TEXT_VISIBLE_ALPHA_THRESHOLD = 0.0


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
        event_publisher: IEventPublisher | None = None,
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
        self._event_publisher = event_publisher
        
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
        self._video_reveal_parked = False
        
        # Text Overlay State
        self._overlay_config = self._build_overlay_config(text_string="")
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
        if isinstance(media_item, DisplayItem):
            media_item = media_item.primary
        if not media_item or getattr(media_item, "filepath", "").endswith("no_pictures.jpg"):
            return ""
            
        if not self._config.show_text_enabled:
            return ""
            
        show_text_config = self._config.text_overlay_format.lower()
        show_text_fm = self._config.show_text_fm
            
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
            location = apply_geo_suppress_list(
                media_item.location,
                self._config.geo_suppress_list,
            )
            if location:
                parts.append(location)
            
        return " - ".join(parts)

    def _generate_text_strings(self, media_item: Any) -> tuple[str, ...]:
        """Generate one or two text overlay strings for the current display item."""
        if isinstance(media_item, DisplayItem) and media_item.layout == DisplayLayout.PORTRAIT_PAIR:
            return tuple(self._generate_text_string(item) for item in media_item.items)
        text = self._generate_text_string(media_item)
        return (text,) if text else ()

    def _handle_config_event(self, event: Any) -> None:
        if not isinstance(event, RendererConfigUpdatedEvent):
            return
            
        self._logger.info("Renderer received RendererConfigUpdatedEvent. Updating state.")
        self._config = event.config
        self._display_x = self._config.display_x
        self._display_y = self._config.display_y
        self._display_w = self._config.display_w
        self._display_h = self._config.display_h
        self._fps = self._config.fps
        self._background = self._config.background
        self._use_glx = self._config.use_glx
        self._use_sdl2 = self._config.use_sdl2
        self._shader_path = os.path.expanduser(self._config.shader_path)
        self._kenburns = self._config.kenburns

        anim_config = {
            "fps": self._config.fps,
            "time_fade": self._config.time_fade,
            "time_delay": self._config.time_delay,
            "show_text_tm": self._config.show_text_tm,
            "kenburns": self._config.kenburns,
        }
        self._animation_controller.update_config(anim_config)
        if self._image_renderer:
            self._image_renderer.update_config(self._config)
        
        old_text_string = self._overlay_config.text_string
        new_text_string = old_text_string
        new_text_strings: tuple[str, ...] = ()
        
        if self._current_media:
            new_text_strings = self._generate_text_strings(self._current_media)
            new_text_string = new_text_strings[0] if new_text_strings else ""
            
        self._overlay_config = self._build_overlay_config(
            text_string=new_text_string,
            text_strings=new_text_strings if len(new_text_strings) == 2 else (),
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
                new_text_strings = self._generate_text_strings(self._current_media)
                new_text_string = new_text_strings[0] if new_text_strings else ""
                if (
                    new_text_string != self._overlay_config.text_string
                    or new_text_strings != self._overlay_config.text_strings
                ):
                    self._overlay_config = self._build_overlay_config(
                        text_string=new_text_string,
                        text_strings=new_text_strings if len(new_text_strings) == 2 else (),
                    )
                    if self._text_renderer:
                        self._text_renderer.update_config(self._overlay_config)
                    self._animation_controller.force_redraw(2)
                    self._animation_controller.update_text_config(True, True)

    def _prepare_wayland_window_identity(self) -> None:
        """Give the SDL/pi3d Wayland window a stable app-id for labwc rules."""
        for key in (
            "SDL_VIDEO_WAYLAND_WMCLASS",
            "SDL_VIDEO_X11_WMCLASS",
            "SDL_APP_ID",
        ):
            os.environ[key] = PI3D_LABWC_IDENTIFIER

    def _build_overlay_config(
        self,
        *,
        text_string: str = "",
        text_strings: tuple[str, ...] = (),
    ) -> OverlayConfig:
        return OverlayConfig(
            show_clock=self._config.show_clock,
            clock_format=self._config.clock_format,
            clock_justify=self._config.clock_justify,
            clock_text_sz=self._config.clock_text_sz,
            clock_opacity=self._config.clock_opacity,
            clock_top_bottom=self._config.clock_top_bottom,
            clock_wdt_offset_pct=self._config.clock_wdt_offset_pct,
            clock_hgt_offset_pct=self._config.clock_hgt_offset_pct,
            show_text=self._config.show_text_enabled,
            text_string=text_string,
            text_strings=text_strings,
            text_justify=self._config.text_justify,
            show_text_sz=self._config.show_text_sz,
            text_bkg_hgt=self._config.text_bkg_hgt,
            text_opacity=self._config.text_opacity,
            text_x_margin=self._config.text_x_margin,
            text_y_margin=self._config.text_y_margin,
        )

    def _prepare_labwc_geometry_rules(self) -> None:
        """Write Picframe's labwc rules so pi3d follows configured geometry."""
        if "WAYLAND_DISPLAY" not in os.environ:
            return
        geometry = self._configured_labwc_geometry()
        labwc_pid = self._find_labwc_pid()
        if labwc_pid is None:
            self._logger.debug("No labwc ancestor found; skipping labwc geometry rules.")
            return

        config_dir = self._labwc_config_dir()
        try:
            config_dir.mkdir(parents=True, exist_ok=True)
            config_path = config_dir / "rc.xml"
            config_path.write_text(
                self._labwc_config_xml(geometry),
                encoding="utf-8",
            )
        except OSError as exc:
            self._logger.warning("Could not write labwc geometry rules: %s", exc)
            return

        try:
            os.kill(labwc_pid, signal.SIGHUP)
            time.sleep(0.05)
            if geometry is None:
                self._logger.info(
                    "Configured labwc fullscreen/default rules for pi3d."
                )
            else:
                self._logger.info(
                    "Configured labwc geometry for pi3d at %s,%s %sx%s.",
                    geometry[0],
                    geometry[1],
                    geometry[2],
                    geometry[3],
                )
        except OSError as exc:
            self._logger.warning("Could not ask labwc to reload geometry rules: %s", exc)

    def _configured_labwc_geometry(self) -> tuple[int, int, int, int] | None:
        if self._display_w is None or self._display_h is None:
            return None
        try:
            x = int(self._display_x)
            y = int(self._display_y)
            w = int(self._display_w)
            h = int(self._display_h)
        except (TypeError, ValueError):
            return None
        if w <= 0 or h <= 0:
            return None
        return (x, y, w, h)

    def _labwc_config_dir(self) -> Path:
        base_dir = Path(os.environ.get("PICFRAME_DIR", "~/.picframe")).expanduser()
        return base_dir / "labwc"

    def _find_labwc_pid(self) -> int | None:
        pid = os.getpid()
        seen: set[int] = set()
        while pid > 1 and pid not in seen:
            seen.add(pid)
            try:
                comm = Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip()
                if comm == "labwc":
                    return pid
                status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
            except OSError:
                return None

            parent_pid = None
            for line in status.splitlines():
                if line.startswith("PPid:"):
                    parent_pid = int(line.split()[1])
                    break
            if parent_pid is None or parent_pid == pid:
                return None
            pid = parent_pid
        return None

    @staticmethod
    def _labwc_window_rule_xml(
        *,
        match_attribute: str,
        match_value: str,
        x: int | None = None,
        y: int | None = None,
        w: int | None = None,
        h: int | None = None,
    ) -> str:
        actions = ""
        if x is not None and y is not None and w is not None and h is not None:
            actions = (
                f'\n      <action name="ResizeTo" width="{w}" height="{h}" />'
                f'\n      <action name="MoveTo" x="{x}" y="{y}" />'
                "\n    "
            )
        return (
            f'    <windowRule {match_attribute}="{match_value}"\n'
            '                serverDecoration="no"\n'
            '                skipTaskbar="yes"\n'
            '                skipWindowSwitcher="yes"\n'
            f'                fixedPosition="yes">{actions}</windowRule>'
        )

    @classmethod
    def _labwc_config_xml(
        cls,
        geometry: tuple[int, int, int, int] | None,
    ) -> str:
        x = y = w = h = None
        if geometry is not None:
            x, y, w, h = geometry

        pi3d_identifier_rule = cls._labwc_window_rule_xml(
            match_attribute="identifier",
            match_value=PI3D_LABWC_IDENTIFIER,
            x=x,
            y=y,
            w=w,
            h=h,
        )
        pi3d_title_rule = cls._labwc_window_rule_xml(
            match_attribute="title",
            match_value=PI3D_LABWC_IDENTIFIER,
            x=x,
            y=y,
            w=w,
            h=h,
        )
        video_rule = cls._labwc_window_rule_xml(
            match_attribute="title",
            match_value=VIDEO_WINDOW_TITLE,
        )
        return (
            "<?xml version=\"1.0\"?>\n"
            "<labwc_config>\n"
            "  <windowRules>\n"
            f"{pi3d_identifier_rule}\n"
            f"{pi3d_title_rule}\n"
            f"{video_rule}\n"
            "  </windowRules>\n"
            "</labwc_config>\n"
        )

    def start(self) -> None:
        """Initialize the pi3d display and sprite."""
        self._logger.info("Starting Pi3dRenderer")
        self._prepare_wayland_window_identity()
        self._prepare_labwc_geometry_rules()
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
                self._overlay_config,
                text_string=command.overlay.text_string,
                text_strings=command.overlay.text_strings,
            )
            
        try:
            if command.image_path == "SUSPEND":
                self._animation_controller.suspend()
                return
            elif command.image_path == "RESUME":
                self._video_reveal_parked = False
                self._image_renderer.clear_video_reveal_texture()
                self._animation_controller.resume()
                self._animation_controller.force_redraw(RESUME_REDRAW_FRAMES)
                return
            elif command.render_action == RENDER_PRELOAD_VIDEO_REVEAL:
                if self._image_renderer.preload_video_reveal_texture(command):
                    self._logger.debug("Preloaded video reveal texture: %s", command.image_path)
                return
            elif command.render_action == RENDER_PROMOTE_VIDEO_REVEAL:
                self._video_reveal_parked = False
                if self._image_renderer.promote_video_reveal_texture():
                    self._animation_controller.resume()
                    self._animation_controller.force_redraw(RESUME_REDRAW_FRAMES)
                    self._logger.debug("Promoted preloaded video reveal texture.")
                else:
                    self._logger.debug("No preloaded video reveal texture to promote.")
                return
            elif command.render_action == RENDER_PARK_VIDEO_REVEAL:
                self._video_reveal_parked = True
                self._logger.debug("Parked pi3d video reveal surface without hard suspend.")
                return
            elif command.render_action == RENDER_WAKE_VIDEO_REVEAL:
                self._video_reveal_parked = False
                self._animation_controller.resume()
                self._animation_controller.force_redraw(RESUME_REDRAW_FRAMES)
                self._logger.debug("Woke parked pi3d video reveal surface for EOS handoff.")
                return

            # Delegate to ImageRenderer
            success, kb_xstep, kb_ystep = self._image_renderer.execute(command)
            if success:
                self._video_reveal_parked = False
                if getattr(command, "background_only", False):
                    self._logger.debug("Loaded image into background buffer only.")
                    self._animation_controller.force_redraw(2)
                    # Ensure we wake up from SUSPENDED state to process the redraw
                    from picframe.core.renderers.animation_controller import RenderState
                    if self._animation_controller._state == RenderState.SUSPENDED:
                        self._animation_controller.resume()
                        # We need to suspend again after drawing the background
                        import threading
                        threading.Timer(0.5, self._animation_controller.suspend).start()
                else:
                    self._animation_controller.start_transition(time.time(), kb_xstep, kb_ystep)
                    self._was_transitioning = True
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

    def get_display_rect(self) -> tuple[int, int, int, int]:
        """Get the actual (x, y, width, height) of the rendering display."""
        if self._display_w and self._display_h:
            return (
                int(self._display_x),
                int(self._display_y),
                int(self._display_w),
                int(self._display_h),
            )

        if self._display is None:
            return (self._display_x, self._display_y, self._display_w or 0, self._display_h or 0)
        
        x = getattr(self._display, 'left', self._display_x)
        y = getattr(self._display, 'top', self._display_y)
        return (int(x), int(y), int(self._display.width), int(self._display.height))

    def render_frame(self) -> bool:
        """
        Draw the current frame and update transition state.
        """
        if self._display is None or self._image_renderer is None:
            return False
            
        tm = time.time()
        anim_state = self._animation_controller.update(tm)
        previous_text_alpha = getattr(self, "_last_text_alpha", -1.0)

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

        if self._video_reveal_parked and anim_state.frames_to_render <= 0:
            time.sleep(0.05)
            return True

        # Sleep optimization for SUSPENDED state
        if anim_state.render_state == RenderState.SUSPENDED:
            time.sleep(0.1)
            return True

        needs_redraw = False
        
        # 1. Check animation and transition states
        if (anim_state.render_state in (RenderState.TRANSITIONING, RenderState.TEXT_ANIMATING) or
            self._kenburns or
            anim_state.frames_to_render > 0 or
            anim_state.text_alpha != previous_text_alpha):
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
            # If we just finished a transition, we need to emit the event
            if getattr(self, '_was_transitioning', False) and anim_state.render_state == RenderState.STATIC:
                from picframe.core.events.dto import TransitionCompletedEvent
                if self._event_publisher is not None:
                    self._event_publisher.publish(TransitionCompletedEvent())
                self._was_transitioning = False
            time.sleep(0.05) # Yield CPU to OS
            return True      # Keep PlaybackEngine loop alive

        # --- ACTIVE RENDER BLOCK ---
        loop_running = self._display.loop_running()
        if not loop_running:
            return False

        self._last_redraw_time = tm
        self._last_text_alpha = anim_state.text_alpha
        text_finished_fading_out = previous_text_alpha > 0.0 and anim_state.text_alpha <= 0.0
        if text_finished_fading_out:
            self._animation_controller.force_redraw(TEXT_CLEAR_REDRAW_FRAMES)

        # Check for transition completion
        if anim_state.render_state == RenderState.STATIC and getattr(self, '_was_transitioning', False):
            if self._event_publisher is not None:
                from picframe.core.events.dto import TransitionCompletedEvent
                self._event_publisher.publish(TransitionCompletedEvent())
            self._was_transitioning = False

        self._last_render_state = anim_state.render_state

        # Apply animation state to components
        self._image_renderer.set_alpha(anim_state.image_alpha)
        if self._kenburns:
            self._image_renderer.set_kenburns_offsets(anim_state.kenburns_x, anim_state.kenburns_y)
            
        if self._text_renderer:
            self._text_renderer.set_alpha(anim_state.text_alpha)

        # Draw components
        self._image_renderer.draw()
        
        if (
            self._text_renderer
            and self._overlay_config.show_text
            and anim_state.text_alpha > TEXT_VISIBLE_ALPHA_THRESHOLD
        ):
            self._text_renderer.draw()
            
        if self._clock_renderer and self._overlay_config.show_clock:
            self._clock_renderer.draw()

        return True
