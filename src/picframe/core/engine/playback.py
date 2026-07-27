"""
Playback Engine for orchestrating media playback and rendering.
"""

import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from picframe.core.events.dto import (
    RENDER_PARK_VIDEO_REVEAL,
    RENDER_PAUSE_PLAYBACK,
    RENDER_PRELOAD_VIDEO_REVEAL,
    RENDER_PROMOTE_VIDEO_REVEAL,
    RENDER_RESUME_PLAYBACK,
    RENDER_UPDATE_OVERLAY,
    RENDER_VIDEO_FIRST_FRAME,
    RENDER_WAKE_VIDEO_REVEAL,
    Command,
    CommandEvent,
    CurrentMediaChangedEvent,
    PlaybackCompletedEvent,
    RenderCommand,
    RendererConfig,
    RendererConfigUpdatedEvent,
    State,
    StateEvent,
    SystemErrorEvent,
    TransitionCompletedEvent,
    VideoFirstFrameRenderedEvent,
    VideoPlaybackWarningEvent,
)
from picframe.core.events.interfaces import IEventPublisher, IEventSubscriber
from picframe.core.exceptions import MediaProcessingError
from picframe.core.models.media import DisplayItem, DisplayLayout, MediaItem
from picframe.core.renderers.interfaces import IRenderer
from picframe.core.services.locale_utils import (
    format_datetime_for_locale,
    language_from_locale,
)
from picframe.core.services.overlay_text import apply_geo_suppress_list
from picframe.core.services.playlist import PlaylistManager
from picframe.core.services.renderer_assets import format_renderer_asset_issues

VIDEO_TRANSITION_FRAME_LOAD_TIMEOUT_SECONDS = 0.5
VIDEO_TRANSITION_FRAME_GENERATE_TIMEOUT_SECONDS = 20.0
VIDEO_REVEAL_SETTLE_FRAMES = 5
VIDEO_REVEAL_SETTLE_TIMEOUT_SECONDS = 0.5
VIDEO_REVEAL_EOS_REDRAW_SECONDS = 0.25
PAUSED_STATUS_TEXT = "PAUSED"


class PlaybackEngine:
    """
    Core state machine for media playback.

    Listens to the Event Bus for commands, requests media from the
    PlaylistManager, and sends RenderCommands to the Renderer.
    """

    def __init__(
        self,
        event_publisher: IEventPublisher,
        event_subscriber: IEventSubscriber,
        playlist_manager: PlaylistManager,
        renderer: IRenderer,
        config: dict[str, Any],
        config_repository: Any | None = None,
        video_player: Any | None = None,
        cache_dir: str | None = None,
        renderer_config: RendererConfig | None = None,
        renderer_asset_validator: Callable[[RendererConfig], list[Any]] | None = None,
    ) -> None:
        """
        Initialize the PlaybackEngine.

        Args:
            event_bus: The central event bus for publishing and subscribing.
            playlist_manager: Service for retrieving media items.
            renderer: The presentation layer component for drawing pixels.
            config: Application configuration.
            config_repository: Optional repository to fetch live configuration updates.
        """
        self._logger = logging.getLogger(__name__)
        self._event_publisher = event_publisher
        self._event_subscriber = event_subscriber
        self._playlist_manager = playlist_manager
        self._renderer = renderer
        self._video_player = video_player
        self._config = config
        self._config_repository = config_repository
        self._cache_dir = cache_dir
        self._renderer_config = renderer_config
        self._renderer_asset_validator = renderer_asset_validator or (lambda _config: [])

        self._state = State.IDLE
        self._is_running = False
        self._renderer_started = False
        self._playlist_ready = False
        self._renderer_retry_requested = False
        self._state_payload: Any = None
        self._time_delay = float(config.get("time_delay", 200.0))
        self._next_transition_time = 0.0
        self._video_first_frame_timeout = float(config.get("video_first_frame_timeout", 2.0))
        self._video_software_fallback_first_frame_timeout = float(
            config.get("video_software_fallback_first_frame_timeout", 8.0)
        )
        self._video_frame_load_lock = threading.Lock()
        self._video_frame_load_in_progress = False
        self._video_reveal_park_pending = False
        self._video_reveal_park_frames = 0
        self._video_reveal_park_started_at = 0.0
        self._video_handoff_sequence = 0
        self._paused_from_state: State | None = None

        # Circuit breaker state
        self._consecutive_errors = 0
        self._max_consecutive_errors = 5

        # Subscribe to commands
        self._event_subscriber.subscribe(CommandEvent, self._handle_command)
        self._event_subscriber.subscribe(StateEvent, self._handle_state_event)

        # Playback events are handled directly by the EventBus worker, matching the
        # stable baseline behavior.
        self._event_subscriber.subscribe(
            PlaybackCompletedEvent,
            self._handle_playback_completed,
        )
        self._event_subscriber.subscribe(
            TransitionCompletedEvent,
            self._handle_transition_completed,
        )
        self._event_subscriber.subscribe(
            VideoFirstFrameRenderedEvent,
            self._handle_video_first_frame_rendered,
        )
        self._event_subscriber.subscribe(
            VideoPlaybackWarningEvent,
            self._handle_video_playback_warning,
        )
        self._event_subscriber.subscribe(
            RendererConfigUpdatedEvent,
            self._handle_renderer_config_event,
        )

    def start(self) -> None:
        """Start the playback engine and render loop."""
        self._logger.info("Starting PlaybackEngine")
        self._is_running = True
        if self._try_start_renderer():
            self._prepare_playback_after_renderer_start()

        # Main render loop
        self._run_loop()

    def _prepare_playback_after_renderer_start(self) -> None:
        """Build playlist and enter playback once the renderer is ready."""
        self._playlist_manager.build_playlist()
        self._playlist_ready = True
        self._consecutive_errors = 0
        self._change_state(State.PLAYING, payload=None)
        self._next_transition_time = 0.0

    def _renderer_error_payload(self, message: str) -> dict[str, Any]:
        return {
            "component": "Pi3dRenderer",
            "reason": "invalid_renderer_config",
            "message": message,
        }

    def _publish_renderer_blocked(self, message: str) -> None:
        self._logger.error("Renderer blocked: %s", message)
        self._renderer_started = False
        self._playlist_ready = False
        self._renderer_retry_requested = False
        self._event_publisher.publish(
            SystemErrorEvent(
                message=message,
                component="Pi3dRenderer",
                sticky=True,
                code="invalid_renderer_config",
            )
        )
        self._change_state(State.ERROR, payload=self._renderer_error_payload(message))

    def _try_start_renderer(self) -> bool:
        """Validate renderer assets and start pi3d on the main thread."""
        if self._renderer_config is not None:
            try:
                issues = self._renderer_asset_validator(self._renderer_config)
            except Exception as error:
                self._publish_renderer_blocked(str(error))
                return False
            if issues:
                self._publish_renderer_blocked(format_renderer_asset_issues(issues))
                return False

        try:
            self._renderer.start()
        except Exception as error:
            self._renderer.stop()
            self._publish_renderer_blocked(str(error))
            return False

        self._renderer_started = True
        self._renderer_retry_requested = False
        return True

    def _restart_renderer(self) -> bool:
        """Stop transient playback state and recreate pi3d on the main thread."""
        self._logger.info("Restarting renderer after config update.")
        self._cancel_video_reveal_parking()
        self._clear_pending_video_preparation()
        for attr in ("_active_video_media", "_active_video_uses_reveal_sandwich"):
            if hasattr(self, attr):
                delattr(self, attr)
        if self._video_player:
            self._video_player.stop()
        self._renderer.stop()
        self._renderer_started = False
        if self._try_start_renderer():
            self._prepare_playback_after_renderer_start()
            return True
        return False

    def _refresh_playback_after_live_renderer_config(self) -> None:
        """Prepare playback after renderer config changed without remapping the display."""
        self._logger.info(
            "Renderer config applied without display restart; scheduling fresh media render."
        )
        self._cancel_video_reveal_parking()
        self._clear_pending_video_preparation()
        for attr in ("_active_video_media", "_active_video_uses_reveal_sandwich"):
            if hasattr(self, attr):
                delattr(self, attr)
        if self._video_player:
            self._video_player.stop()
        if self._state in (State.PREPARING_VIDEO, State.TRANSITIONING, State.PLAYING):
            self._change_state(State.PLAYING, payload=None)
        self._next_transition_time = 0.0

    def stop(self) -> None:
        """Stop the playback engine and render loop."""
        self._logger.info("Stopping PlaybackEngine")
        self._is_running = False
        self._clear_pending_video_preparation()
        self._cancel_video_reveal_parking()
        if hasattr(self, "_active_video_media"):
            delattr(self, "_active_video_media")
        if self._video_player:
            self._video_player.stop()
        # We don't call renderer.stop() here because it might be called
        # from a signal handler which can cause issues with pi3d's
        # display destruction. The renderer will be stopped when the
        # run loop exits.
        self._change_state(State.IDLE)

    def _run_loop(self) -> None:
        """The main synchronous render loop."""
        while self._is_running:
            try:
                # 2. Check if it\'s time for the next slide
                current_time = time.time()

                if not self._renderer_started:
                    if self._renderer_retry_requested and self._try_start_renderer():
                        self._prepare_playback_after_renderer_start()
                    else:
                        time.sleep(0.1)
                    continue

                if self._renderer_retry_requested:
                    self._restart_renderer()
                    continue

                self._handle_video_first_frame_timeout(current_time)
                if self._state == State.PLAYING and current_time >= self._next_transition_time:
                    self._trigger_next_media()

                # 3. Render the frame
                if not self._renderer.render_frame():
                    self._logger.info("Renderer requested exit")
                    self._is_running = False
                    break
                self._update_video_reveal_parking(current_time)

                # Reset error counter on successful loop iteration
                self._consecutive_errors = 0

            except MediaProcessingError as e:
                self._handle_media_error(e)
            except Exception as e:
                self._handle_system_error(e)

            # Small sleep to prevent 100% CPU usage if renderer doesn't block
            time.sleep(0.01)

        self._logger.info("Exiting render loop, stopping renderer")
        self._renderer.stop()

    def _start_video_reveal_parking(self) -> None:
        self._video_reveal_park_pending = True
        self._video_reveal_park_frames = 0
        self._video_reveal_park_started_at = time.time()
        self._logger.debug(
            "Started video reveal parking countdown: %d frames or %.2fs timeout.",
            VIDEO_REVEAL_SETTLE_FRAMES,
            VIDEO_REVEAL_SETTLE_TIMEOUT_SECONDS,
        )

    def _cancel_video_reveal_parking(self) -> None:
        self._video_reveal_park_pending = False
        self._video_reveal_park_frames = 0
        self._video_reveal_park_started_at = 0.0

    def _update_video_reveal_parking(self, current_time: float) -> None:
        if not self._video_reveal_park_pending:
            return
        if self._state != State.PLAYING or not hasattr(self, "_active_video_media"):
            self._cancel_video_reveal_parking()
            return

        self._video_reveal_park_frames += 1
        elapsed = current_time - self._video_reveal_park_started_at
        if self._video_reveal_park_frames >= VIDEO_REVEAL_SETTLE_FRAMES:
            self._park_video_reveal("frames rendered")
        elif elapsed >= VIDEO_REVEAL_SETTLE_TIMEOUT_SECONDS:
            self._park_video_reveal("timeout")

    def _park_video_reveal(self, reason: str) -> None:
        self._logger.debug("Parking pi3d video reveal after %s.", reason)
        self._renderer.execute(
            RenderCommand(
                image_path="PARK_VIDEO_REVEAL",
                render_action=RENDER_PARK_VIDEO_REVEAL,
            )
        )
        self._cancel_video_reveal_parking()

    def _handle_command(self, event: CommandEvent) -> None:
        """Handle incoming commands from the Event Bus."""
        self._logger.debug(f"Received command: {event.command}")

        if (
            not self._renderer_started
            and self._state == State.ERROR
            and event.command in (Command.NEXT, Command.PREV, Command.PLAY)
        ):
            self._renderer_retry_requested = True
            return

        # If we are preparing a video, we need to handle interruptions gracefully
        if self._state == State.PREPARING_VIDEO and event.command in (
            Command.NEXT,
            Command.PREV,
            Command.STOP,
        ):
            self._logger.info(f"Interrupting video preparation with command: {event.command}")
            self._cancel_video_reveal_parking()
            self._clear_pending_video_preparation()
            if self._video_player:
                self._video_player.stop()
            self._change_state(State.IDLE)

        if event.command == Command.NEXT:
            self._trigger_next_media()
        elif event.command == Command.PREV:
            self._trigger_prev_media()
        elif event.command == Command.PAUSE:
            if self._state == State.PAUSED:
                self._resume_playback()
            elif self._state in (
                State.PLAYING,
                State.TRANSITIONING,
                State.PREPARING_VIDEO,
            ):
                self._pause_playback()
        elif event.command == Command.PLAY:
            self._resume_playback()
        elif event.command == Command.STOP:
            self.stop()
        elif event.command == Command.DELETE:
            self._handle_delete_command(event.payload)
        elif event.command == Command.PURGE_FILES:
            self._handle_purge_command()
        elif event.command == Command.REQUEST_STATE:
            self._handle_request_state()
        elif event.command == Command.SET_VOL:
            if self._video_player and event.payload is not None:
                self._video_player.set_volume(float(event.payload))

    def _has_active_video_playback(self) -> bool:
        return hasattr(self, "_active_video_media")

    def _has_pending_video_playback_started(self) -> bool:
        return bool(getattr(self, "_pending_video_playback_started", False))

    def _pause_playback(self) -> None:
        self._paused_from_state = self._state
        active_video = self._has_active_video_playback()
        pending_video = self._has_pending_video_playback_started()
        if self._video_player and (active_video or pending_video):
            self._video_player.pause()
            self._set_video_pause_overlay(True, PAUSED_STATUS_TEXT)
        render_action = RENDER_UPDATE_OVERLAY if active_video else RENDER_PAUSE_PLAYBACK
        self._send_status_overlay(PAUSED_STATUS_TEXT, render_action=render_action)
        self._change_state(State.PAUSED)

    def _resume_playback(self) -> None:
        paused_from_state = self._paused_from_state
        self._paused_from_state = None
        active_video = self._has_active_video_playback()
        pending_video = self._has_pending_video_playback_started()
        if active_video:
            render_action = (
                RENDER_RESUME_PLAYBACK
                if paused_from_state == State.PREPARING_VIDEO
                else RENDER_UPDATE_OVERLAY
            )
            self._send_status_overlay("", render_action=render_action)
            self._set_video_pause_overlay(False, "")
            self._change_state(State.PLAYING)
            self._next_transition_time = float("inf")
            if paused_from_state == State.PREPARING_VIDEO and getattr(
                self, "_active_video_uses_reveal_sandwich", False
            ):
                self._start_video_reveal_parking()
            if self._video_player:
                self._video_player.resume()
            return
        if pending_video:
            self._send_status_overlay("", render_action=RENDER_RESUME_PLAYBACK)
            self._set_video_pause_overlay(False, "")
            self._change_state(State.PREPARING_VIDEO)
            if self._video_player:
                self._video_player.resume()
            return

        self._send_status_overlay("", render_action=RENDER_RESUME_PLAYBACK)
        if paused_from_state in (State.PREPARING_VIDEO, State.TRANSITIONING):
            self._change_state(paused_from_state)
            return
        self._change_state(State.PLAYING)
        self._next_transition_time = time.time() + self._time_delay

    def _handle_state_event(self, event: StateEvent) -> None:
        """React to runtime configuration changes."""
        if event.state != State.CONFIG_CHANGED:
            return
        payload = event.payload if isinstance(event.payload, dict) else {}
        updated_sections = payload.get("updated_sections", [])

        if "model" in updated_sections:
            self._refresh_model_timing()
            if self._renderer_started:
                self._playlist_manager.build_playlist()
                self._playlist_ready = True
            if self._state == State.PLAYING and self._next_transition_time != float("inf"):
                self._next_transition_time = min(
                    self._next_transition_time,
                    time.time() + self._time_delay,
                )

        if "viewer" in updated_sections:
            self._refresh_video_renderer_settings()

    def _refresh_video_renderer_settings(self) -> None:
        """Refresh video-player settings that can be applied without pi3d restart."""
        if self._config_repository is None or self._video_player is None:
            return
        setter = getattr(self._video_player, "set_max_software_decode_resolution", None)
        if setter is None:
            return
        setter(
            str(
                self._config_repository.get_app_config(
                    "viewer.max_software_decode_resolution",
                    "1280x720",
                )
            )
        )

    def _handle_renderer_config_event(self, event: RendererConfigUpdatedEvent) -> None:
        """Record renderer config updates; main loop performs renderer work."""
        if not isinstance(event, RendererConfigUpdatedEvent):
            return

        old_config = self._renderer_config
        old_live_signature = self._renderer_live_refresh_signature(old_config)
        new_live_signature = self._renderer_live_refresh_signature(event.config)
        old_geometry_signature = self._renderer_geometry_signature(old_config)
        new_geometry_signature = self._renderer_geometry_signature(event.config)
        self._renderer_config = event.config
        if not self._renderer_started:
            self._renderer_retry_requested = True
            return

        restart_required = self._renderer.requires_restart_for_config(
            old_config,
            event.config,
        )
        if restart_required:
            self._logger.info(
                "Renderer config contains changes that require Picframe service restart; "
                "skipping in-process renderer restart."
            )
            self._renderer_retry_requested = False
            return

        live_changed = old_live_signature != new_live_signature
        geometry_changed = old_geometry_signature != new_geometry_signature
        if live_changed or geometry_changed:
            self._renderer_retry_requested = False
            self._refresh_playback_after_live_renderer_config()
            return
        self._renderer_retry_requested = False

    @staticmethod
    def _renderer_geometry_signature(config: RendererConfig | None) -> tuple[Any, ...] | None:
        """Return display rectangle fields from renderer config."""
        if config is None:
            return None
        return (
            config.display_x,
            config.display_y,
            config.display_w,
            config.display_h,
        )

    @staticmethod
    def _renderer_live_refresh_signature(config: RendererConfig | None) -> tuple[Any, ...] | None:
        """Return config fields that should repaint current media without process restart."""
        if config is None:
            return None
        return (
            config.fps,
            config.background,
            config.shader_path,
            config.kenburns,
            config.show_clock,
            config.clock_format,
            config.clock_justify,
            config.clock_text_sz,
            config.clock_opacity,
            config.clock_top_bottom,
            config.clock_wdt_offset_pct,
            config.clock_hgt_offset_pct,
            config.show_text_enabled,
            config.text_overlay_format,
            config.show_text_fm,
            config.model_locale,
            config.text_justify,
            config.show_text_sz,
            config.text_bkg_hgt,
            config.text_opacity,
            config.text_x_margin,
            config.text_y_margin,
            tuple(config.geo_suppress_list),
            config.time_fade,
            config.time_delay,
            config.show_text_tm,
            config.font_file,
            config.blend_type,
            config.blur_amount,
            config.blur_zoom,
            config.blur_edges,
            config.edge_alpha,
            config.fit,
            config.video_fit_display,
            tuple(config.video_extensions),
            config.mat_images,
            config.mat_type,
            config.outer_mat_color,
            config.inner_mat_color,
            config.outer_mat_border,
            config.inner_mat_border,
            config.outer_mat_use_texture,
            config.inner_mat_use_texture,
            config.mat_resource_folder,
        )

    def _configured_display_rect(self) -> tuple[int, int, int, int] | None:
        if self._config_repository is None:
            return None
        try:
            raw_w = self._config_repository.get_app_config("viewer.display_w")
            raw_h = self._config_repository.get_app_config("viewer.display_h")
            if raw_w in (None, "") or raw_h in (None, ""):
                return None
            w = int(raw_w)
            h = int(raw_h)
            if w <= 0 or h <= 0:
                return None
            x = int(self._config_repository.get_app_config("viewer.display_x", 0) or 0)
            y = int(self._config_repository.get_app_config("viewer.display_y", 0) or 0)
            return (x, y, w, h)
        except (TypeError, ValueError) as exc:
            self._logger.warning("Ignoring invalid configured display rectangle: %s", exc)
            return None

    def _configured_display_is_fullscreen(self) -> bool:
        if self._config_repository is None:
            return False
        try:
            raw_w = self._config_repository.get_app_config("viewer.display_w")
            raw_h = self._config_repository.get_app_config("viewer.display_h")
            if raw_w not in (None, "") or raw_h not in (None, ""):
                return False
            x = int(self._config_repository.get_app_config("viewer.display_x", 0) or 0)
            y = int(self._config_repository.get_app_config("viewer.display_y", 0) or 0)
            return x == 0 and y == 0
        except (TypeError, ValueError) as exc:
            self._logger.warning("Ignoring invalid fullscreen display rectangle: %s", exc)
            return False

    def _video_frame_dimensions(self) -> tuple[int, int]:
        renderer_x, renderer_y, renderer_w, renderer_h = self._renderer.get_display_rect()
        if renderer_w > 0 and renderer_h > 0:
            return renderer_w, renderer_h
        configured_rect = self._configured_display_rect()
        if configured_rect is not None:
            self._logger.info(
                "Using configured video frame dimensions %sx%s because renderer "
                "reported invalid rect %s,%s %sx%s.",
                configured_rect[2],
                configured_rect[3],
                renderer_x,
                renderer_y,
                renderer_w,
                renderer_h,
            )
            return configured_rect[2], configured_rect[3]
        return renderer_w, renderer_h

    def _video_display_rect(self) -> tuple[int, int, int, int]:
        renderer_rect = self._renderer.get_display_rect()
        if self._configured_display_is_fullscreen():
            self._logger.info(
                "Using fullscreen video handoff for renderer display rect %s.",
                renderer_rect,
            )
            return (0, 0, 0, 0)

        configured_rect = self._configured_display_rect()
        if configured_rect is None:
            return renderer_rect
        renderer_x, renderer_y, renderer_w, renderer_h = renderer_rect
        if renderer_w > 0 and renderer_h > 0:
            if configured_rect != renderer_rect:
                self._logger.info(
                    "Using renderer-reported video display rect %s instead of configured rect %s.",
                    renderer_rect,
                    configured_rect,
                )
            return renderer_rect
        if configured_rect != renderer_rect:
            self._logger.info(
                "Using configured video display rect %s because renderer reported invalid rect %s.",
                configured_rect,
                renderer_rect,
            )
        return configured_rect

    def _video_fit_display(self) -> bool:
        """Return whether videos should be scaled to the display dimensions."""
        if self._config_repository:
            return self._config_repository.get_app_config_bool(
                "viewer.video_fit_display",
                bool(self._config.get("video_fit_display", False)),
            )
        return bool(self._config.get("video_fit_display", False))

    def _video_host_background(self) -> tuple[float, ...] | None:
        if self._renderer_config is None:
            return None
        return tuple(self._renderer_config.background)

    def _video_matting_config(self) -> Any:
        return self._renderer_config

    def _video_edge_config(self) -> Any:
        return self._renderer_config

    def _video_display_origin(self) -> tuple[int, int]:
        x, y, w, h = self._video_display_rect()
        if w > 0 and h > 0:
            return x, y
        renderer_x, renderer_y, renderer_w, renderer_h = self._renderer.get_display_rect()
        if renderer_w > 0 and renderer_h > 0:
            return renderer_x, renderer_y
        configured_rect = self._configured_display_rect()
        if configured_rect is not None:
            return configured_rect[0], configured_rect[1]
        return 0, 0

    def _video_content_rect_from_metadata(
        self,
        metadata: Any | None,
    ) -> tuple[int, int, int, int] | None:
        content_rect = getattr(metadata, "content_rect", None)
        try:
            content_x, content_y, content_w, content_h = (
                int(content_rect[0]),
                int(content_rect[1]),
                int(content_rect[2]),
                int(content_rect[3]),
            )
        except (TypeError, ValueError, IndexError):
            return None
        if content_w <= 0 or content_h <= 0:
            return None

        coordinate_space = getattr(metadata, "coordinate_space", "frame_pixels")
        if coordinate_space != "frame_pixels":
            return None

        frame_size = getattr(metadata, "frame_size", None)
        if frame_size is not None:
            try:
                frame_w, frame_h = int(frame_size[0]), int(frame_size[1])
            except (TypeError, ValueError, IndexError):
                return None
            if (
                frame_w <= 0
                or frame_h <= 0
                or content_x < 0
                or content_y < 0
                or content_x + content_w > frame_w
                or content_y + content_h > frame_h
            ):
                return None

        return content_x, content_y, content_w, content_h

    def _video_display_rect_for_metadata(self, metadata: Any | None) -> tuple[int, int, int, int]:
        content_rect = self._video_content_rect_from_metadata(metadata)
        if content_rect is None:
            return self._video_display_rect()
        content_x, content_y, content_w, content_h = content_rect
        origin_x, origin_y = self._video_display_origin()
        return (
            origin_x + content_x,
            origin_y + content_y,
            content_w,
            content_h,
        )

    def _video_backdrop_rect_for_metadata(
        self,
        metadata: Any | None,
    ) -> tuple[int, int, int, int] | None:
        if not getattr(metadata, "backdrop", getattr(metadata, "matted", False)):
            return None
        origin_x, origin_y = self._video_display_origin()
        display_w, display_h = self._video_frame_dimensions()
        if display_w <= 0 or display_h <= 0:
            return None
        return (origin_x, origin_y, display_w, display_h)

    def _play_video(
        self,
        media_item: MediaItem,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        host_backdrop_path: str | None = None,
        host_backdrop_rect: tuple[int, int, int, int] | None = None,
        content_fit: str | None = None,
    ) -> None:
        if not self._video_player:
            return
        kwargs: dict[str, Any] = {}
        if host_backdrop_path:
            kwargs["host_backdrop_path"] = host_backdrop_path
            kwargs["host_backdrop_rect"] = host_backdrop_rect
        if content_fit is not None:
            kwargs["content_fit"] = content_fit
        self._video_player.play(
            media_item,
            x,
            y,
            w,
            h,
            self._video_fit_display(),
            self._video_host_background(),
            **kwargs,
        )

    def _refresh_model_timing(self) -> None:
        """Refresh playback timing values from live configuration."""
        if self._config_repository:
            self._time_delay = float(
                self._config_repository.get_app_config(
                    "model.time_delay", self._config.get("time_delay", 200.0)
                )
            )
            self._config["fade_time"] = float(
                self._config_repository.get_app_config(
                    "model.fade_time", self._config.get("fade_time", 10.0)
                )
            )
            self._config["video_extensions"] = self._config_repository.get_app_config(
                "model.video_extensions",
                self._config.get("video_extensions", [".mp4", ".mov", ".mkv", ".avi", ".webm"]),
            )
        else:
            self._time_delay = float(self._config.get("time_delay", 200.0))

    @staticmethod
    def _as_display_item(item: Any) -> DisplayItem | None:
        """Normalize legacy single MediaItem values to DisplayItem."""
        if item is None:
            return None
        if isinstance(item, DisplayItem):
            return item
        if isinstance(item, MediaItem):
            return DisplayItem.single(item)
        return None

    @staticmethod
    def _is_video_media(media_item: MediaItem, video_extensions: tuple[str, ...]) -> bool:
        """Return True when the media item should use the video path."""
        return media_item.filepath.lower().endswith(video_extensions)

    def _build_overlay_config(self, display_item: DisplayItem) -> Any:
        """Build overlay configuration for single or pair display items."""
        from picframe.core.events.dto import OverlayConfig

        def config_value(key: str, legacy_key: str, default: Any) -> Any:
            if self._config_repository:
                return self._config_repository.get_app_config(
                    key,
                    self._config.get(legacy_key, default),
                )
            return self._config.get(legacy_key, default)

        def config_bool(key: str, legacy_key: str, default: bool) -> bool:
            if self._config_repository:
                return self._config_repository.get_app_config_bool(
                    key,
                    bool(self._config.get(legacy_key, default)),
                )
            raw_value = self._config.get(legacy_key, default)
            if isinstance(raw_value, str):
                return raw_value.lower() in {"1", "true", "yes", "on", "t", "y"}
            return bool(raw_value)

        show_clock = config_bool("viewer.show_clock", "show_clock", False)
        clock_format = str(config_value("viewer.clock_format", "clock_format", "%H:%M"))
        show_text = config_bool(
            "viewer.show_text_enabled",
            "show_text_enabled",
            self._text_overlay_enabled(self._config.get("show_text", False)),
        )

        text_strings = tuple(self._generate_text_string(item) for item in display_item.items)
        return OverlayConfig(
            show_clock=show_clock,
            clock_format=clock_format,
            clock_justify=str(config_value("viewer.clock_justify", "clock_justify", "R")),
            clock_text_sz=int(config_value("viewer.clock_text_sz", "clock_text_sz", 120)),
            clock_opacity=float(config_value("viewer.clock_opacity", "clock_opacity", 1.0)),
            clock_top_bottom=str(config_value("viewer.clock_top_bottom", "clock_top_bottom", "T")),
            clock_wdt_offset_pct=float(
                config_value("viewer.clock_wdt_offset_pct", "clock_wdt_offset_pct", 3.0)
            ),
            clock_hgt_offset_pct=float(
                config_value("viewer.clock_hgt_offset_pct", "clock_hgt_offset_pct", 3.0)
            ),
            show_text=show_text,
            text_string=text_strings[display_item.primary_index] if text_strings else "",
            text_strings=text_strings if display_item.layout == DisplayLayout.PORTRAIT_PAIR else (),
            text_justify=str(config_value("viewer.text_justify", "text_justify", "L")),
            show_text_sz=int(config_value("viewer.show_text_sz", "show_text_sz", 40)),
            text_bkg_hgt=float(config_value("viewer.text_bkg_hgt", "text_bkg_hgt", 0.25)),
            text_opacity=float(config_value("viewer.text_opacity", "text_opacity", 1.0)),
            text_x_margin=int(config_value("viewer.text_x_margin", "text_x_margin", 100)),
            text_y_margin=int(config_value("viewer.text_y_margin", "text_y_margin", 0)),
        )

    def _overlay_config_for_current_status(self, status_text: str) -> Any:
        """Build a status overlay without forcing metadata text on."""
        from picframe.core.events.dto import OverlayConfig

        current_display = self._as_display_item(self._playlist_manager.get_current())
        base_overlay = (
            self._build_overlay_config(current_display)
            if current_display is not None
            else OverlayConfig()
        )
        return replace(base_overlay, status_text=status_text)

    def _send_status_overlay(
        self,
        status_text: str,
        *,
        render_action: str = RENDER_UPDATE_OVERLAY,
    ) -> None:
        overlay_config = self._overlay_config_for_current_status(status_text)
        self._renderer.execute(
            RenderCommand(
                image_path=render_action,
                overlay=overlay_config,
                render_action=render_action,
            )
        )

    def _set_video_pause_overlay(self, visible: bool, text: str = "") -> None:
        if self._video_player is None:
            return
        set_pause_overlay = getattr(self._video_player, "set_pause_overlay", None)
        if callable(set_pause_overlay):
            set_pause_overlay(visible, text)

    @staticmethod
    def _text_overlay_enabled(raw_value: Any) -> bool:
        """Parse boolean or legacy text-format overlay settings."""
        if isinstance(raw_value, bool):
            return raw_value
        value = str(raw_value).strip().lower()
        return value not in {"", "0", "false", "off", "none", "no"}

    def _text_overlay_format(self) -> str:
        """Return the active text overlay format with legacy fallback."""
        default_format = self._config.get(
            "text_overlay_format",
            self._config.get("show_text", ""),
        )

        if self._config_repository:
            text_format = str(
                self._config_repository.get_app_config(
                    "viewer.text_overlay_format",
                    default_format,
                )
            ).strip()
            if text_format:
                return text_format.lower()

            legacy_format = str(
                self._config_repository.get_app_config(
                    "viewer.show_text",
                    default_format,
                )
            ).strip()
            return legacy_format.lower()

        return str(default_format).strip().lower()

    @staticmethod
    def _pair_render_command(display_item: DisplayItem, overlay_config: Any) -> RenderCommand:
        """Build a render command for an in-memory portrait pair."""
        return RenderCommand(
            image_path=display_item.primary.filepath,
            overlay=overlay_config,
            layout=display_item.layout.value,
            image_paths=tuple(item.filepath for item in display_item.items),
        )

    def _handle_request_state(self) -> None:
        """Handle a request to broadcast the current state and media."""
        self._event_publisher.publish(StateEvent(state=self._state, payload=self._state_payload))
        if not self._renderer_started:
            return
        current_display = self._as_display_item(self._playlist_manager.get_current())
        if current_display:
            self._event_publisher.publish(CurrentMediaChangedEvent(media_item=current_display))
        else:
            # If there's no current media (e.g., on startup before the first transition),
            # try to get the next one to populate the initial state.
            # We don't trigger a full transition here, just fetch the data.
            if self._playlist_manager._display_playlist:
                # Peek at the first item without advancing the index
                if self._playlist_manager._current_index < len(
                    self._playlist_manager._display_playlist
                ):
                    slot_data = self._playlist_manager._display_playlist[
                        self._playlist_manager._current_index
                    ]
                    display_item = self._playlist_manager._slot_to_display_item(slot_data)
                    self._event_publisher.publish(CurrentMediaChangedEvent(media_item=display_item))
            else:
                # Fallback to placeholder if playlist is empty
                placeholder = self._playlist_manager._get_no_images_placeholder()
                self._event_publisher.publish(
                    CurrentMediaChangedEvent(media_item=DisplayItem.single(placeholder))
                )

    def _handle_delete_command(self, payload: Any = None) -> None:
        """Handle the DELETE command by moving the current file and advancing."""
        import os
        import shutil

        current_display = self._as_display_item(self._playlist_manager.get_current())
        if not current_display or current_display.id == 0:
            self._logger.warning("No active media to delete.")
            return

        delete_payload = payload if isinstance(payload, dict) else {}
        target = str(delete_payload.get("target", "left"))
        raw_media_ids = delete_payload.get("media_ids")
        media_ids = (
            [int(media_id) for media_id in raw_media_ids]
            if isinstance(raw_media_ids, list)
            else None
        )

        delete_ids = self._playlist_manager.resolve_current_delete_ids(target, media_ids)
        if not delete_ids:
            message = "Delete request did not match the current display item."
            self._logger.warning(message)
            self._event_publisher.publish(
                SystemErrorEvent(message=message, component="PlaybackEngine")
            )
            return

        items_by_id = {int(item.id): item for item in current_display.items if item.id is not None}

        # Determine deleted directory
        if self._config_repository:
            deleted_dir_config = self._config_repository.get_app_config(
                "model.deleted_pictures",
                self._config.get("deleted_pictures", "~/DeletedPictures"),
            )
        else:
            deleted_dir_config = self._config.get("deleted_pictures", "~/DeletedPictures")

        deleted_dir = os.path.expanduser(deleted_dir_config)

        moved_ids: list[int] = []
        try:
            os.makedirs(deleted_dir, exist_ok=True)
            for media_id in delete_ids:
                media_item = items_by_id.get(media_id)
                if media_item is None:
                    self._logger.warning(
                        "Delete target is no longer in the current display item: %s",
                        media_id,
                    )
                    continue

                filepath = media_item.filepath
                if not os.path.exists(filepath):
                    self._logger.warning(f"File to delete not found: {filepath}")
                    continue

                filename = os.path.basename(filepath)
                dest_path = os.path.join(deleted_dir, filename)

                shutil.move(filepath, dest_path)
                moved_ids.append(media_id)
                self._logger.info(f"Moved deleted file to: {dest_path}")

            if not moved_ids:
                self._logger.warning("No files were deleted for the current delete request.")
                return

            self._playlist_manager.delete_media_ids(moved_ids)

            # Immediately transition to next media
            self._trigger_next_media()

        except Exception as e:
            self._logger.error(f"Failed to delete current media: {e}")

    def _handle_purge_command(self) -> None:
        """Handle the PURGE_FILES command by cleaning up the database."""
        self._logger.info("Executing PURGE_FILES command.")
        purged_count = self._playlist_manager.purge_missing_files()
        self._logger.info(f"Purged {purged_count} missing files from database.")

        if self._renderer_started:
            # Rebuild playlist to ensure we don't try to play purged items.
            self._playlist_manager.build_playlist()
            self._playlist_ready = True
        else:
            self._playlist_ready = False

    def _video_extensions(self) -> tuple[str, ...]:
        return tuple(
            ext.lower()
            for ext in self._config.get(
                "video_extensions",
                [".mp4", ".mov", ".mkv", ".avi", ".webm"],
            )
        )

    def _cached_video_transition_metadata(
        self,
        extractor: Any,
        first_frame_path: str,
    ) -> Any | None:
        cache_validator = getattr(extractor, "cached_transition_frames_valid", None)
        if callable(cache_validator):
            cache_valid = cache_validator()
            if isinstance(cache_valid, bool) and not cache_valid:
                return None

        metadata = getattr(extractor, "last_transition_metadata", None)
        if metadata is None:
            metadata_loader = getattr(extractor, "_load_transition_metadata", None)
            if callable(metadata_loader):
                metadata = metadata_loader()
        if metadata is None:
            return None

        with_backdrop_path = getattr(metadata, "with_backdrop_path", None)
        if callable(with_backdrop_path):
            return with_backdrop_path(first_frame_path)
        return metadata

    def _video_backdrop_path_for_metadata(
        self,
        metadata: Any | None,
        fallback_path: str | None = None,
    ) -> str | None:
        if not getattr(metadata, "backdrop", getattr(metadata, "matted", False)):
            return None
        return getattr(metadata, "backdrop_path", None) or fallback_path

    def _start_video_handoff(
        self,
        media_item: MediaItem,
        overlay_config: dict[str, Any] | None,
    ) -> bool:
        if not self._video_player or not self._is_video_media(
            media_item,
            self._video_extensions(),
        ):
            return False

        from picframe.core.utils.video_frame_extractor import VideoFrameExtractor

        base, _ = os.path.splitext(media_item.filepath)
        first_frame_path = base + ".1.frame"
        last_frame_path = base + ".2.frame"
        duration = getattr(media_item, "duration", 0.0) or 0.0
        display_w, display_h = self._video_frame_dimensions()
        first_img = None
        last_img = None
        metadata = None

        if duration > 0 and display_w > 0 and display_h > 0:
            try:
                extractor = VideoFrameExtractor(
                    media_item.filepath,
                    display_w,
                    display_h,
                    fit_display=self._video_fit_display(),
                    cache_dir=self._cache_dir,
                    background=self._video_host_background(),
                    matting_config=self._video_matting_config(),
                    edge_config=self._video_edge_config(),
                )
                first_frame_path = extractor.get_frame_path("first")
                last_frame_path = extractor.get_frame_path("last")
                metadata = self._cached_video_transition_metadata(
                    extractor,
                    first_frame_path,
                )
                self._logger.info(
                    "Loading or generating video transition frames for %s at "
                    "%sx%s with %.2fs budget.",
                    media_item.filepath,
                    display_w,
                    display_h,
                    VIDEO_TRANSITION_FRAME_LOAD_TIMEOUT_SECONDS,
                )
                frames = self._load_video_transition_frames_with_deadline(
                    extractor,
                    duration,
                    display_w,
                    display_h,
                )
                if frames:
                    first_img, last_img = frames
                    metadata = extractor.last_transition_metadata or metadata
            except Exception as e:
                self._logger.error(
                    "Failed to extract frames for %s: %s",
                    media_item.filepath,
                    e,
                )

        if first_img is not None:
            self._video_handoff_sequence += 1
            transition_token = self._video_handoff_sequence
            self._pending_video_media = media_item
            self._pending_first_frame_path = first_frame_path
            self._pending_last_img = last_img
            self._pending_last_frame_path = last_frame_path
            self._pending_video_transition_metadata = metadata
            self._pending_video_transition_token = transition_token
            self._pending_video_backdrop_path = self._video_backdrop_path_for_metadata(
                metadata, first_frame_path
            )
            self._pending_video_backdrop_rect = self._video_backdrop_rect_for_metadata(metadata)
            self._next_transition_time = float("inf")
            self._change_state(State.PREPARING_VIDEO)

            self._logger.debug("Sending first frame to renderer: %s", first_frame_path)
            self._renderer.execute(
                RenderCommand(
                    image_path=first_frame_path,
                    overlay=overlay_config,
                    image_obj=first_img,
                    render_action=RENDER_VIDEO_FIRST_FRAME,
                    transition_token=transition_token,
                )
            )
            return True

        self._logger.warning(
            "Could not generate first frame for %s; playing video directly.",
            media_item.filepath,
        )
        self._renderer.execute(RenderCommand(image_path="RESUME", overlay=overlay_config))
        x, y, w, h = self._video_display_rect_for_metadata(metadata)
        self._play_video(
            media_item,
            x,
            y,
            w,
            h,
            host_backdrop_path=self._video_backdrop_path_for_metadata(
                metadata,
                first_frame_path,
            ),
            host_backdrop_rect=self._video_backdrop_rect_for_metadata(metadata),
            content_fit=(
                "fill" if self._video_content_rect_from_metadata(metadata) is not None else None
            ),
        )
        self._active_video_media = media_item
        self._active_video_uses_reveal_sandwich = False
        self._next_transition_time = float("inf")
        self._change_state(State.PLAYING)
        return True

    def _trigger_next_media(self) -> None:
        """Fetch the next media item and send a render command."""
        if not self._renderer_started and self._state == State.ERROR:
            self._renderer_retry_requested = True
            return

        self._cancel_video_reveal_parking()
        self._clear_pending_video_preparation()
        if hasattr(self, "_active_video_media"):
            delattr(self, "_active_video_media")
        if hasattr(self, "_active_video_uses_reveal_sandwich"):
            delattr(self, "_active_video_uses_reveal_sandwich")

        display_item = self._as_display_item(self._playlist_manager.get_next())
        if display_item:
            media_item = display_item.primary
            self._logger.info(
                "Transitioning to next display item: %s",
                ", ".join(item.filepath for item in display_item.items),
            )
            self._change_state(State.TRANSITIONING)

            overlay_config = self._build_overlay_config(display_item)

            if self._start_video_handoff(media_item, overlay_config):
                pass
            else:
                if self._video_player:
                    self._video_player.stop()
                if display_item.layout == DisplayLayout.PORTRAIT_PAIR:
                    render_cmd = self._pair_render_command(display_item, overlay_config)
                else:
                    render_cmd = RenderCommand(
                        image_path=media_item.filepath,
                        overlay=overlay_config,
                    )
                try:
                    self._renderer.execute(render_cmd)
                    # Update timer for images
                    self._next_transition_time = time.time() + self._time_delay
                    self._change_state(State.PLAYING)
                except MediaProcessingError as e:
                    self._handle_media_error(e)

            # Publish media changed event
            self._event_publisher.publish(CurrentMediaChangedEvent(media_item=display_item))
        else:
            self._logger.warning("No media available to play")

    def _handle_transition_completed(self, event: Any) -> None:
        """Handle the completion of a visual transition."""
        if self._state == State.PREPARING_VIDEO and hasattr(self, "_pending_video_media"):
            event_token = getattr(event, "transition_token", None)
            pending_token = getattr(self, "_pending_video_transition_token", None)
            if (
                event_token is not None
                and pending_token is not None
                and event_token != pending_token
            ):
                self._logger.debug(
                    "Ignoring stale video transition completion token %s; pending token is %s.",
                    event_token,
                    pending_token,
                )
                return
            self._logger.info("First frame transition completed, starting video playback.")
            if self._video_player:
                self._preload_pending_video_reveal_frame()
                metadata = getattr(self, "_pending_video_transition_metadata", None)
                x, y, w, h = self._video_display_rect_for_metadata(metadata)
                self._play_video(
                    self._pending_video_media,
                    x,
                    y,
                    w,
                    h,
                    host_backdrop_path=getattr(self, "_pending_video_backdrop_path", None),
                    host_backdrop_rect=getattr(self, "_pending_video_backdrop_rect", None),
                    content_fit=(
                        "fill"
                        if self._video_content_rect_from_metadata(metadata) is not None
                        else None
                    ),
                )
                self._pending_video_playback_started = True
                self._video_first_frame_deadline = time.time() + self._video_first_frame_timeout
            # We don't change state to PLAYING yet. We wait for VideoFirstFrameRenderedEvent.
            # This ensures pi3d stays opaque until GStreamer is actually rendering.
        elif self._state == State.TRANSITIONING:
            self._change_state(State.PLAYING)

    def _handle_video_first_frame_rendered(self, event: Any) -> None:
        """Handle the event indicating GStreamer has rendered its first frame."""
        self._complete_video_first_frame_handoff()

    def _handle_video_playback_warning(self, event: Any) -> None:
        """Give fallback decoder startup a longer first-frame window."""
        if (
            self._state != State.PREPARING_VIDEO
            or not hasattr(self, "_pending_video_media")
            or getattr(event, "warning_type", None) != "software_fallback"
        ):
            return

        current_deadline = getattr(self, "_video_first_frame_deadline", None)
        fallback_deadline = time.time() + self._video_software_fallback_first_frame_timeout
        self._video_first_frame_deadline = max(
            current_deadline or 0.0,
            fallback_deadline,
        )
        self._logger.info(
            "Extended GStreamer first-frame deadline for software decoder fallback: %s",
            getattr(event, "decoder", "unknown"),
        )

    def _load_video_transition_frames_with_deadline(
        self,
        extractor: Any,
        duration: float,
        display_w: int,
        display_h: int,
    ) -> Any | None:
        """Load cached video transition frames without blocking playback indefinitely."""
        with self._video_frame_load_lock:
            if self._video_frame_load_in_progress:
                self._logger.warning(
                    "Skipping cached video transition frames; previous frame load is still running."
                )
                return None
            self._video_frame_load_in_progress = True

        result: dict[str, Any] = {}
        first_path = extractor.get_frame_path("first")
        last_path = extractor.get_frame_path("last")
        cache_valid: Any = None
        cache_validator = getattr(extractor, "cached_transition_frames_valid", None)
        if callable(cache_validator):
            cache_valid = cache_validator()
        if isinstance(cache_valid, bool):
            frames_missing = not cache_valid
        else:
            frames_missing = not (os.path.exists(first_path) and os.path.exists(last_path))
        timeout_seconds = (
            VIDEO_TRANSITION_FRAME_GENERATE_TIMEOUT_SECONDS
            if frames_missing
            else VIDEO_TRANSITION_FRAME_LOAD_TIMEOUT_SECONDS
        )

        def load_frames() -> None:
            try:
                result["frames"] = extractor.get_first_and_last_frames(
                    duration,
                    display_w,
                    display_h,
                    extract_missing=True,
                )
            except Exception as exc:
                result["error"] = exc
            finally:
                with self._video_frame_load_lock:
                    self._video_frame_load_in_progress = False

        loader = threading.Thread(
            target=load_frames,
            name="picframe-video-frame-loader",
            daemon=True,
        )
        loader.start()
        loader.join(timeout_seconds)
        if loader.is_alive():
            self._logger.warning(
                "Timed out %s video transition frames after %.2fs; playing video directly.",
                "generating" if frames_missing else "loading cached",
                timeout_seconds,
            )
            return None

        error = result.get("error")
        if error is not None:
            raise error
        return result.get("frames")

    def _handle_video_first_frame_timeout(self, current_time: float) -> None:
        """Avoid getting stuck if GStreamer does not report first-frame readiness."""
        deadline = getattr(self, "_video_first_frame_deadline", None)
        if (
            self._state == State.PREPARING_VIDEO
            and deadline is not None
            and current_time >= deadline
        ):
            self._logger.warning(
                "Timed out waiting for GStreamer first-frame event; continuing video handoff."
            )
            self._complete_video_first_frame_handoff()

    def _complete_video_first_frame_handoff(self) -> None:
        """Reveal video playback after GStreamer has presented its first frame."""
        handoff_paused = (
            self._state == State.PAUSED
            and self._paused_from_state == State.PREPARING_VIDEO
            and self._has_pending_video_playback_started()
        )
        if (self._state == State.PREPARING_VIDEO or handoff_paused) and hasattr(
            self, "_pending_video_media"
        ):
            self._logger.info("GStreamer first frame rendered, fading out pi3d.")
            media_item = self._pending_video_media
            self._active_video_media = media_item
            reveal_promoted = self._promote_pending_video_reveal_frame()
            self._active_video_uses_reveal_sandwich = reveal_promoted
            if not handoff_paused:
                self._change_state(State.PLAYING)
            if reveal_promoted and not handoff_paused:
                self._start_video_reveal_parking()
            self._clear_pending_video_preparation()

    def _preload_pending_video_reveal_frame(self) -> None:
        """Preload the cached last frame before the GTK video window covers pi3d."""
        last_img = getattr(self, "_pending_last_img", None)
        last_frame_path = getattr(self, "_pending_last_frame_path", None)
        if last_img is None or not last_frame_path:
            return

        self._logger.debug("Preloading video reveal texture: %s", last_frame_path)
        self._renderer.execute(
            RenderCommand(
                image_path=last_frame_path,
                image_obj=last_img,
                render_action=RENDER_PRELOAD_VIDEO_REVEAL,
            )
        )

    def _promote_pending_video_reveal_frame(self) -> bool:
        """Promote the preloaded last frame after GStreamer is visibly rendering."""
        last_frame_path = getattr(self, "_pending_last_frame_path", "") or ""
        if not last_frame_path:
            return False

        self._logger.debug("Promoting video reveal texture: %s", last_frame_path)
        self._renderer.execute(
            RenderCommand(
                image_path=last_frame_path,
                render_action=RENDER_PROMOTE_VIDEO_REVEAL,
            )
        )
        return True

    def _handle_playback_completed(self, event: Any) -> None:
        """Handle the completion of video playback."""
        self._logger.info("Video playback completed, scheduling transition to next media.")
        self._cancel_video_reveal_parking()
        if self._state == State.PREPARING_VIDEO and hasattr(self, "_pending_video_media"):
            self._logger.warning("Video playback completed before first-frame handoff.")
            self._clear_pending_video_preparation()
            self._change_state(State.PLAYING)

        uses_reveal_sandwich = getattr(self, "_active_video_uses_reveal_sandwich", False)
        if hasattr(self, "_active_video_media"):
            delattr(self, "_active_video_media")
        if hasattr(self, "_active_video_uses_reveal_sandwich"):
            delattr(self, "_active_video_uses_reveal_sandwich")

        if uses_reveal_sandwich:
            self._renderer.execute(
                RenderCommand(
                    image_path="WAKE_VIDEO_REVEAL",
                    render_action=RENDER_WAKE_VIDEO_REVEAL,
                )
            )
            time.sleep(VIDEO_REVEAL_EOS_REDRAW_SECONDS)
        else:
            self._renderer.execute(RenderCommand(image_path="RESUME", overlay=None))

        if self._video_player:
            self._video_player.stop()

        self._next_transition_time = 0.0

    def _trigger_prev_media(self) -> None:
        """Fetch the previous media item and send a render command."""
        self._cancel_video_reveal_parking()
        self._clear_pending_video_preparation()
        if hasattr(self, "_active_video_media"):
            delattr(self, "_active_video_media")
        if hasattr(self, "_active_video_uses_reveal_sandwich"):
            delattr(self, "_active_video_uses_reveal_sandwich")

        display_item = self._as_display_item(self._playlist_manager.get_previous())
        if display_item:
            media_item = display_item.primary
            self._logger.info(
                "Transitioning to previous display item: %s",
                ", ".join(item.filepath for item in display_item.items),
            )
            self._change_state(State.TRANSITIONING)

            overlay_config = self._build_overlay_config(display_item)

            if self._start_video_handoff(media_item, overlay_config):
                pass
            else:
                if self._video_player:
                    self._video_player.stop()
                if display_item.layout == DisplayLayout.PORTRAIT_PAIR:
                    render_cmd = self._pair_render_command(display_item, overlay_config)
                else:
                    render_cmd = RenderCommand(
                        image_path=media_item.filepath,
                        overlay=overlay_config,
                    )
                try:
                    self._renderer.execute(render_cmd)
                    self._next_transition_time = time.time() + self._time_delay
                except MediaProcessingError as e:
                    self._handle_media_error(e)
                else:
                    self._change_state(State.PLAYING)

            # Publish media changed event
            self._event_publisher.publish(CurrentMediaChangedEvent(media_item=display_item))
        else:
            self._logger.warning("No previous media available")

    def _clear_pending_video_preparation(self) -> None:
        """Clear cached first-frame handoff state for an unstarted video."""
        for attr in (
            "_pending_video_media",
            "_pending_first_frame_path",
            "_pending_last_img",
            "_pending_last_frame_path",
            "_video_first_frame_deadline",
            "_pending_video_transition_metadata",
            "_pending_video_transition_token",
            "_pending_video_backdrop_path",
            "_pending_video_backdrop_rect",
            "_pending_video_playback_started",
        ):
            if hasattr(self, attr):
                delattr(self, attr)

    def _generate_text_string(self, media_item: Any) -> str:
        """Generate the text overlay string based on configuration and media metadata."""
        # If it's the fallback image, don't show any text
        if media_item.filepath.endswith("no_pictures.jpg"):
            return ""

        # Fetch live configuration from the repository, or use the initial config.
        if self._config_repository:
            show_text_enabled = self._config_repository.get_app_config_bool(
                "viewer.show_text_enabled",
                self._text_overlay_enabled(self._config.get("show_text", False)),
            )
            show_text_config = self._text_overlay_format()
            show_text_fm = str(
                self._config_repository.get_app_config(
                    "viewer.show_text_fm", self._config.get("show_text_fm", "%b %d, %Y")
                )
            )
            model_locale = str(
                self._config_repository.get_app_config(
                    "model.locale", self._config.get("locale", "en_US.utf8")
                )
            )
        else:
            show_text_enabled = self._text_overlay_enabled(
                self._config.get("show_text_enabled", self._config.get("show_text", False))
            )
            show_text_config = self._text_overlay_format()
            show_text_fm = str(self._config.get("show_text_fm", "%b %d, %Y"))
            model_locale = str(self._config.get("locale", "en_US.utf8"))

        if not show_text_enabled or not self._text_overlay_enabled(show_text_config):
            return ""

        parts = []

        if "title" in show_text_config and getattr(media_item, "title", None):
            parts.append(media_item.title)

        if "caption" in show_text_config and getattr(media_item, "caption", None):
            parts.append(media_item.caption)

        if "name" in show_text_config and getattr(media_item, "filename", None):
            parts.append(media_item.filename)

        if "date" in show_text_config:
            # Prefer EXIF datetime; fall back to file last_modified (#714).
            date_timestamp = getattr(media_item, "exif_datetime", None)
            if not date_timestamp:
                date_timestamp = getattr(media_item, "last_modified", None)
            if date_timestamp:
                import datetime

                try:
                    dt = datetime.datetime.fromtimestamp(date_timestamp)
                    parts.append(format_datetime_for_locale(dt, show_text_fm, model_locale))
                except Exception:
                    pass

        if "folder" in show_text_config and getattr(media_item, "filepath", None):
            import os

            parts.append(os.path.basename(os.path.dirname(media_item.filepath)))

        if "location" in show_text_config:
            location = getattr(media_item, "location", None)
            if (
                not location
                and getattr(media_item, "latitude", None) is not None
                and getattr(media_item, "longitude", None) is not None
            ):
                # Check if it's in the database cache first
                location_language = language_from_locale(model_locale)
                cached_location = self._playlist_manager._media_repo.get_location(
                    media_item.latitude,
                    media_item.longitude,
                    language=location_language,
                )
                if cached_location:
                    location = cached_location
                    media_item.location = location
                else:
                    # Enqueue for background processing
                    self._playlist_manager._media_repo.enqueue_location_lookup(
                        media_item.latitude,
                        media_item.longitude,
                        language=location_language,
                    )

            if location:
                if self._config_repository:
                    raw_suppress_list = self._config_repository.get_app_config(
                        "viewer.geo_suppress_list",
                        self._config.get("geo_suppress_list", []),
                    )
                else:
                    raw_suppress_list = self._config.get("geo_suppress_list", [])
                suppress_list = (
                    raw_suppress_list
                    if isinstance(raw_suppress_list, list)
                    else [raw_suppress_list]
                    if raw_suppress_list
                    else []
                )
                location = apply_geo_suppress_list(location, suppress_list)
                if location:
                    parts.append(location)

        return " - ".join(parts)

    def _handle_media_error(self, error: Exception) -> None:
        """Handle a recoverable media processing error."""
        self._logger.error(f"Media processing error: {error}", exc_info=True)
        self._consecutive_errors += 1

        self._event_publisher.publish(
            SystemErrorEvent(message=str(error), component="PlaybackEngine")
        )

        if self._consecutive_errors >= self._max_consecutive_errors:
            self._logger.critical("Circuit breaker tripped: Too many consecutive media errors.")
            self._change_state(State.ERROR)
            self._is_running = False
        else:
            self._logger.info("Attempting to recover by skipping to next media.")
            self._change_state(State.IDLE)
            # Force immediate transition on next loop
            self._next_transition_time = 0.0
            self._change_state(State.PLAYING)

    def _handle_system_error(self, error: Exception) -> None:
        """Handle a critical system error."""
        self._logger.critical(f"Critical system error in render loop: {error}", exc_info=True)
        self._event_publisher.publish(
            SystemErrorEvent(message=f"Critical Error: {error}", component="PlaybackEngine")
        )
        self._change_state(State.ERROR)
        self._is_running = False

    def _change_state(self, new_state: State, payload: Any = None) -> None:
        """Update internal state and publish a StateEvent."""
        if self._state != new_state or self._state_payload != payload:
            self._logger.debug(f"State changed: {self._state} -> {new_state}")
            self._state = new_state
            self._state_payload = payload
            self._event_publisher.publish(StateEvent(state=new_state, payload=payload))
