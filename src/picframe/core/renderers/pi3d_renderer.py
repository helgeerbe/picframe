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
    RENDER_PARK_VIDEO_REVEAL,
    RENDER_PAUSE_PLAYBACK,
    RENDER_PRELOAD_VIDEO_REVEAL,
    RENDER_PROMOTE_VIDEO_REVEAL,
    RENDER_RESUME_PLAYBACK,
    RENDER_UPDATE_OVERLAY,
    RENDER_VIDEO_FIRST_FRAME,
    RENDER_WAKE_VIDEO_REVEAL,
    CurrentMediaChangedEvent,
    OverlayConfig,
    RenderCommand,
    RendererConfig,
    RendererConfigUpdatedEvent,
    TransitionCompletedEvent,
)
from picframe.core.events.interfaces import IEventPublisher, IEventSubscriber
from picframe.core.models.media import DisplayItem, DisplayLayout
from picframe.core.renderers.animation_controller import AnimationController, RenderState
from picframe.core.renderers.components.clock_renderer import ClockRenderer
from picframe.core.renderers.components.image_renderer import ImageRenderer
from picframe.core.renderers.components.text_renderer import TextRenderer
from picframe.core.renderers.interfaces import IRenderer
from picframe.core.services.locale_utils import format_datetime_for_locale
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

    @staticmethod
    def _geometry_signature(config: RendererConfig) -> tuple[Any, ...]:
        """Return display rectangle fields from renderer config."""
        return (
            config.display_x,
            config.display_y,
            config.display_w,
            config.display_h,
        )

    @staticmethod
    def _service_restart_signature(config: RendererConfig) -> tuple[Any, ...]:
        """Return display backend fields that require restarting Picframe."""
        return (
            config.use_glx,
            config.use_sdl2,
        )

    @staticmethod
    def _component_rebuild_signature(config: RendererConfig) -> tuple[Any, ...]:
        """Return component resources that can be rebuilt on the mapped display."""
        return (
            config.shader_path,
            config.font_file,
        )

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
        self._render_rect: tuple[int, int, int, int] | None = None
        self._pending_component_rebuild = False
        self._video_reveal_parked = False
        self._video_first_frame_transition = False
        self._transition_token: int | None = None

        # Text Overlay State
        self._overlay_config = self._build_overlay_config(text_string="")
        self._text_renderer: TextRenderer | None = None
        self._clock_renderer: ClockRenderer | None = None

        self._animation_controller = AnimationController(self._animation_config())
        self._animation_controller.update_text_config(self._overlay_config.show_text, False)

        self._local_queue: queue.PriorityQueue[PrioritizedRenderTask] = queue.PriorityQueue()
        self._current_media: Any | None = None

    def _animation_config(self) -> dict[str, Any]:
        """Return animation settings in the shape expected by AnimationController."""
        return {
            "fps": self._config.fps,
            "time_fade": self._config.time_fade,
            "time_delay": self._config.time_delay,
            "show_text_tm": self._config.show_text_tm,
            "kenburns": self._config.kenburns,
        }

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
                parts.append(
                    format_datetime_for_locale(
                        dt,
                        show_text_fm,
                        self._config.model_locale,
                    )
                )
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
        old_config = self._config
        restart_required = self.requires_restart_for_config(old_config, event.config)
        component_rebuild_required = self._requires_component_rebuild_for_config(
            old_config,
            event.config,
        )
        self._apply_config_state(event.config)
        self._apply_live_display_settings()

        if restart_required:
            self._logger.info(
                "Renderer geometry/backend update requires Picframe service restart; "
                "keeping the active pi3d display mapped with its current resources."
            )
            return

        if component_rebuild_required and self._display is not None:
            self._pending_component_rebuild = True
            self._logger.info(
                "Renderer config update will rebuild pi3d components on the existing display."
            )
            return

        self._apply_live_component_config()

    def _apply_live_component_config(self) -> None:
        """Apply config fields supported by active renderer components."""
        self._animation_controller.update_config(self._animation_config())
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
            self._overlay_config.show_text, self._overlay_config.text_string != old_text_string
        )

    def _apply_live_display_settings(self) -> None:
        """Apply display settings pi3d supports changing on the fly."""
        if self._display is None:
            return
        try:
            self._display.frames_per_second = self._fps
        except Exception as exc:
            self._logger.debug("Could not update pi3d display FPS: %s", exc)

    def _handle_state_event(self, event: Any) -> None:
        if isinstance(event, CurrentMediaChangedEvent):
            self._current_media = event.media_item

            # Update text string when media changes
            if self._config.show_text_enabled:
                new_text_strings = self._generate_text_strings(self._current_media)
                new_text_string = new_text_strings[0] if new_text_strings else ""
                new_overlay_text_strings = new_text_strings if len(new_text_strings) == 2 else ()
                if (
                    new_text_string != self._overlay_config.text_string
                    or new_overlay_text_strings != self._overlay_config.text_strings
                ):
                    self._overlay_config = self._build_overlay_config(
                        text_string=new_text_string,
                        text_strings=new_overlay_text_strings,
                    )
                    if self._text_renderer:
                        self._text_renderer.update_config(self._overlay_config)
                    self._animation_controller.force_redraw(2)
                    self._animation_controller.update_text_config(
                        self._overlay_has_visible_text(),
                        True,
                    )

    def _apply_config_state(self, config: RendererConfig) -> None:
        """Refresh renderer-owned config values without touching active components."""
        self._config = config
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
            clock_extra_source=self._config.clock_extra_source,
            clock_extra_text=self._config.clock_extra_text,
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
                self._logger.info("Configured labwc fullscreen/default rules for pi3d.")
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
        return self._configured_geometry_for_config(self._config)

    @staticmethod
    def _configured_geometry_for_config(config: RendererConfig) -> tuple[int, int, int, int] | None:
        if config.display_w is None or config.display_h is None:
            return None
        try:
            x = int(config.display_x)
            y = int(config.display_y)
            w = int(config.display_w)
            h = int(config.display_h)
        except (TypeError, ValueError):
            return None
        if w <= 0 or h <= 0:
            return None
        return (x, y, w, h)

    def _custom_display_requires_fullscreen_host(self) -> bool:
        return self._custom_display_requires_fullscreen_host_for_config(self._config)

    def _custom_display_requires_fullscreen_host_for_config(
        self,
        config: RendererConfig,
    ) -> bool:
        if "WAYLAND_DISPLAY" not in os.environ:
            return False
        if self._configured_geometry_for_config(config) is None:
            return False
        return self._find_labwc_pid() is None

    def _uses_fullscreen_host_for_config(self, config: RendererConfig) -> bool:
        geometry = self._configured_geometry_for_config(config)
        if geometry is None:
            try:
                x = int(config.display_x)
                y = int(config.display_y)
            except (TypeError, ValueError):
                return False
            return x == 0 and y == 0
        return self._custom_display_requires_fullscreen_host_for_config(config)

    def _render_rect_for_config(self, config: RendererConfig) -> tuple[int, int, int, int] | None:
        geometry = self._configured_geometry_for_config(config)
        if geometry is not None and self._uses_fullscreen_host_for_config(config):
            return geometry
        return None

    def _requires_component_rebuild_for_config(
        self,
        old_config: RendererConfig | None,
        new_config: RendererConfig,
    ) -> bool:
        """Return whether active pi3d components should be recreated."""
        if self._display is None:
            return False
        old_config = old_config or self._config
        if self._component_rebuild_signature(old_config) != self._component_rebuild_signature(
            new_config
        ):
            return True
        if self._geometry_signature(old_config) == self._geometry_signature(new_config):
            return False
        return self._uses_fullscreen_host_for_config(
            old_config
        ) and self._uses_fullscreen_host_for_config(new_config)

    def requires_restart_for_config(
        self,
        old_config: RendererConfig | None,
        new_config: RendererConfig,
    ) -> bool:
        """Return whether a renderer config change needs a pi3d display recreation."""
        if self._display is None:
            return False
        old_config = old_config or self._config
        if self._service_restart_signature(old_config) != self._service_restart_signature(
            new_config
        ):
            return True
        if self._geometry_signature(old_config) == self._geometry_signature(new_config):
            return False
        return not (
            self._uses_fullscreen_host_for_config(old_config)
            and self._uses_fullscreen_host_for_config(new_config)
        )

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
            '<?xml version="1.0"?>\n'
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
        self._reset_start_runtime_state()
        self._prepare_wayland_window_identity()
        self._render_rect = self._render_rect_for_config(self._config)
        self._prepare_labwc_geometry_rules()
        self._logger.debug("Calling pi3d.Display.create...")
        display_x = 0 if self._render_rect is not None else self._display_x
        display_y = 0 if self._render_rect is not None else self._display_y
        display_w = None if self._render_rect is not None else self._display_w
        display_h = None if self._render_rect is not None else self._display_h
        if self._render_rect is not None:
            self._logger.info(
                "Using fullscreen pi3d host with render rect %s,%s %sx%s.",
                self._render_rect[0],
                self._render_rect[1],
                self._render_rect[2],
                self._render_rect[3],
            )
        try:
            self._display = pi3d.Display.create(
                x=display_x,
                y=display_y,
                w=display_w,
                h=display_h,
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

        self._create_render_components()

    def _create_render_components(self) -> None:
        """Create pi3d-dependent render components for the current display."""
        pi3d.Camera(is_3d=False)
        shader = pi3d.Shader(self._shader_path)
        flat_shader = pi3d.Shader("uv_flat")

        self._image_renderer = ImageRenderer(
            self._display,
            shader,
            self._config,
            render_rect=self._render_rect,
        )

        font_file = os.path.expanduser(self._config.font_file)
        self._text_renderer = TextRenderer(
            self._display,
            flat_shader,
            font_file,
            render_rect=self._render_rect,
        )
        self._clock_renderer = ClockRenderer(
            self._display,
            flat_shader,
            font_file,
            render_rect=self._render_rect,
        )

    def stop(self) -> None:
        """Destroy the pi3d display."""
        self._logger.info("Stopping Pi3dRenderer")
        if self._display is not None:
            self._display.destroy()
            self._display = None
        self._image_renderer = None
        self._text_renderer = None
        self._clock_renderer = None
        self._render_rect = None
        self._pending_component_rebuild = False
        self._reset_pi3d_singletons()

    def _reset_start_runtime_state(self) -> None:
        """Reset transient render state whenever a new pi3d display is created."""
        self._video_reveal_parked = False
        self._video_first_frame_transition = False
        self._was_transitioning = False
        self._last_text_alpha = -1.0
        self._last_redraw_time = 0.0
        self._last_render_state = RenderState.STATIC
        self._local_queue = queue.PriorityQueue()
        self._animation_controller = AnimationController(self._animation_config())
        self._animation_controller.update_text_config(
            self._overlay_has_visible_text(),
            False,
        )
        self._animation_controller.force_redraw(RESUME_REDRAW_FRAMES)

    def _sync_overlay_config_for_current_media(self) -> None:
        if not self._current_media:
            self._overlay_config = self._build_overlay_config(text_string="")
            return
        text_strings = self._generate_text_strings(self._current_media)
        text_string = text_strings[0] if text_strings else ""
        self._overlay_config = self._build_overlay_config(
            text_string=text_string,
            text_strings=text_strings if len(text_strings) == 2 else (),
        )

    def _reset_pi3d_camera_singletons(self) -> None:
        """Clear only Camera singleton state before rebuilding components."""
        camera_owner = getattr(pi3d, "Camera", None)
        if camera_owner is None:
            return
        for attr in ("INSTANCE", "_INSTANCE"):
            if hasattr(camera_owner, attr):
                try:
                    setattr(camera_owner, attr, None)
                except Exception as exc:
                    self._logger.debug(
                        "Could not clear pi3d Camera.%s singleton: %s",
                        attr,
                        exc,
                    )
        if hasattr(camera_owner, "_ALL_INSTANCES"):
            try:
                setattr(camera_owner, "_ALL_INSTANCES", set())
            except Exception as exc:
                self._logger.debug(
                    "Could not clear pi3d Camera._ALL_INSTANCES: %s",
                    exc,
                )

    def _rebuild_components_for_existing_display(self) -> None:
        """Recreate render components for a new render rectangle without remapping SDL."""
        if self._display is None:
            self._pending_component_rebuild = False
            return
        self._logger.info("Rebuilding pi3d render components for updated geometry.")
        self._render_rect = self._render_rect_for_config(self._config)
        self._image_renderer = None
        self._text_renderer = None
        self._clock_renderer = None
        self._sync_overlay_config_for_current_media()
        self._reset_pi3d_camera_singletons()
        self._reset_start_runtime_state()
        self._create_render_components()
        if self._text_renderer:
            self._text_renderer.update_config(self._overlay_config)
        if self._clock_renderer:
            self._clock_renderer.update_config(self._overlay_config)
        self._pending_component_rebuild = False

    def _reset_pi3d_singletons(self) -> None:
        """Clear pi3d singleton references that can point at a destroyed display."""
        singleton_owners: list[tuple[str, Any]] = []
        display_owner = getattr(pi3d, "Display", None)
        if display_owner is not None:
            singleton_owners.append(("Display", display_owner))
            display_class = getattr(display_owner, "Display", None)
            if isinstance(display_class, type):
                singleton_owners.append(("Display.Display", display_class))
        camera_owner = getattr(pi3d, "Camera", None)
        if camera_owner is not None:
            singleton_owners.append(("Camera", camera_owner))

        for name, owner in singleton_owners:
            if owner is None:
                continue
            for attr in ("INSTANCE", "_INSTANCE"):
                if hasattr(owner, attr):
                    try:
                        setattr(owner, attr, None)
                    except Exception as exc:
                        self._logger.debug(
                            "Could not clear pi3d %s.%s singleton: %s",
                            name,
                            attr,
                            exc,
                        )
            if hasattr(owner, "_ALL_INSTANCES"):
                try:
                    setattr(owner, "_ALL_INSTANCES", set())
                except Exception as exc:
                    self._logger.debug(
                        "Could not clear pi3d %s._ALL_INSTANCES: %s",
                        name,
                        exc,
                    )

    def _overlay_has_visible_text(self) -> bool:
        if self._overlay_config.status_text:
            return True
        if not self._overlay_config.show_text:
            return False
        if self._overlay_config.text_string:
            return True
        return any(self._overlay_config.text_strings)

    def _transition_completed_ready(self, anim_state: Any) -> bool:
        if not getattr(self, "_was_transitioning", False):
            return False
        if anim_state.render_state != RenderState.STATIC:
            return False
        if not self._video_first_frame_transition:
            return True
        return self._animation_controller.video_handoff_ready(anim_state)

    def _publish_transition_completed_if_ready(self, anim_state: Any) -> None:
        if not self._transition_completed_ready(anim_state):
            return
        if self._event_publisher is not None:
            self._event_publisher.publish(
                TransitionCompletedEvent(transition_token=self._transition_token)
            )
        self._was_transitioning = False
        self._video_first_frame_transition = False
        self._transition_token = None

    def execute(self, command: RenderCommand) -> None:
        """
        Load a new image and initiate a transition.
        """
        if self._display is None:
            self._logger.warning("Renderer not started, ignoring command")
            return
        if self._pending_component_rebuild:
            self._rebuild_components_for_existing_display()
        if self._image_renderer is None:
            self._logger.warning("Renderer image component not ready, ignoring command")
            return

        if command.overlay:
            self._overlay_config = replace(
                self._overlay_config,
                show_text=command.overlay.show_text,
                text_string=command.overlay.text_string,
                text_strings=command.overlay.text_strings,
                status_text=command.overlay.status_text,
            )

        try:
            if command.image_path == "SUSPEND":
                self._animation_controller.suspend()
                return
            elif command.image_path == "RESUME":
                self._video_reveal_parked = False
                self._video_first_frame_transition = False
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
            elif command.render_action == RENDER_PAUSE_PLAYBACK:
                self._animation_controller.update_text_config(
                    self._overlay_has_visible_text(),
                    False,
                )
                self._animation_controller.pause(
                    force_text_visible=bool(self._overlay_config.status_text)
                )
                if self._text_renderer:
                    self._text_renderer.update_config(self._overlay_config)
                if self._clock_renderer:
                    self._clock_renderer.update_config(self._overlay_config)
                self._animation_controller.force_redraw(RESUME_REDRAW_FRAMES)
                return
            elif command.render_action == RENDER_RESUME_PLAYBACK:
                self._animation_controller.update_text_config(
                    self._overlay_has_visible_text(),
                    False,
                )
                self._animation_controller.resume_pause()
                if self._text_renderer:
                    self._text_renderer.update_config(self._overlay_config)
                if self._clock_renderer:
                    self._clock_renderer.update_config(self._overlay_config)
                self._animation_controller.force_redraw(RESUME_REDRAW_FRAMES)
                return
            elif command.render_action == RENDER_UPDATE_OVERLAY:
                self._animation_controller.update_text_config(
                    self._overlay_has_visible_text(),
                    True,
                )
                if self._text_renderer:
                    self._text_renderer.update_config(self._overlay_config)
                if self._clock_renderer:
                    self._clock_renderer.update_config(self._overlay_config)
                self._animation_controller.force_redraw(RESUME_REDRAW_FRAMES)
                return

            # Delegate to ImageRenderer
            is_video_first_frame = command.render_action == RENDER_VIDEO_FIRST_FRAME
            success, kb_xstep, kb_ystep = self._image_renderer.execute(command)
            if success:
                self._video_reveal_parked = False
                if getattr(command, "background_only", False):
                    self._video_first_frame_transition = False
                    self._transition_token = None
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
                    self._video_first_frame_transition = is_video_first_frame
                    self._transition_token = command.transition_token
                    self._animation_controller.start_transition(time.time(), kb_xstep, kb_ystep)
                    self._was_transitioning = True
                    self._animation_controller.update_text_config(
                        self._overlay_has_visible_text(),
                        True,
                    )

                    if self._text_renderer:
                        self._text_renderer.update_config(self._overlay_config)
                    if self._clock_renderer:
                        self._clock_renderer.update_config(self._overlay_config)
            else:
                self._video_first_frame_transition = False
                self._transition_token = None

        except Exception as e:
            self._logger.error(f"Failed to execute RenderCommand: {e}")

    def enqueue_task(self, priority: int, task: Any) -> None:
        """Enqueue a high-frequency task (like a clock tick) for the render loop."""
        self._local_queue.put(PrioritizedRenderTask(priority=priority, task=task))

    def get_display_rect(self) -> tuple[int, int, int, int]:
        """Get the actual (x, y, width, height) of the rendering display."""
        if self._render_rect is not None:
            return self._render_rect
        if self._display is None:
            return (self._display_x, self._display_y, self._display_w or 0, self._display_h or 0)

        x = getattr(self._display, "left", self._display_x)
        y = getattr(self._display, "top", self._display_y)
        return (int(x), int(y), int(self._display.width), int(self._display.height))

    def render_frame(self) -> bool:
        """
        Draw the current frame and update transition state.
        """
        if self._display is None:
            return False
        if self._pending_component_rebuild:
            self._rebuild_components_for_existing_display()
        if self._image_renderer is None:
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

        if self._animation_controller.is_paused and anim_state.frames_to_render <= 0:
            time.sleep(0.05)
            return True

        # Sleep optimization for SUSPENDED state
        if anim_state.render_state == RenderState.SUSPENDED:
            time.sleep(0.1)
            return True

        needs_redraw = False

        # 1. Check animation and transition states
        if (
            anim_state.render_state in (RenderState.TRANSITIONING, RenderState.TEXT_ANIMATING)
            or self._kenburns
            or anim_state.frames_to_render > 0
            or anim_state.text_alpha != previous_text_alpha
        ):
            needs_redraw = True

        # 2. Check dynamic overlays (Clock)
        elif self._clock_renderer:
            if self._clock_renderer.has_changed():
                needs_redraw = True

        # 3. OS Keepalive (prevent Wayland/X11 "Not Responding" hangs)
        elif (tm - getattr(self, "_last_redraw_time", 0)) > 10.0:
            needs_redraw = True

        # --- STATIC BYPASS ---
        if not needs_redraw:
            # If we just finished a transition, we need to emit the event
            self._publish_transition_completed_if_ready(anim_state)
            time.sleep(0.05)  # Yield CPU to OS
            return True  # Keep PlaybackEngine loop alive

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
        self._publish_transition_completed_if_ready(anim_state)

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
            and self._overlay_has_visible_text()
            and anim_state.text_alpha > TEXT_VISIBLE_ALPHA_THRESHOLD
        ):
            self._text_renderer.draw()

        if self._clock_renderer and self._overlay_config.show_clock:
            self._clock_renderer.draw()

        return True
