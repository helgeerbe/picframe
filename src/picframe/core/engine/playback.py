"""
Playback Engine for orchestrating media playback and rendering.
"""
import logging
import time
from collections.abc import Callable
from typing import Any

from picframe.core.events.dto import (
    Command,
    CommandEvent,
    CurrentMediaChangedEvent,
    RenderCommand,
    RendererConfig,
    RendererConfigUpdatedEvent,
    State,
    StateEvent,
    SystemErrorEvent,
)
from picframe.core.events.interfaces import IEventPublisher, IEventSubscriber
from picframe.core.exceptions import MediaProcessingError
from picframe.core.models.media import DisplayItem, DisplayLayout, MediaItem
from picframe.core.renderers.interfaces import IRenderer
from picframe.core.services.playlist import PlaylistManager
from picframe.core.services.renderer_assets import format_renderer_asset_issues


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
        self._texture_swap_time = float("inf")
        self._video_suspend_generation = 0
        
        # Circuit breaker state
        self._consecutive_errors = 0
        self._max_consecutive_errors = 5
        
        # Subscribe to commands
        self._event_subscriber.subscribe(CommandEvent, self._handle_command)
        self._event_subscriber.subscribe(StateEvent, self._handle_state_event)
        
        # Subscribe to video playback completion
        from picframe.core.events.dto import (
            PlaybackCompletedEvent,
            TransitionCompletedEvent,
            VideoFirstFrameRenderedEvent,
            VideoPlaybackWarningEvent,
        )
        self._event_subscriber.subscribe(PlaybackCompletedEvent, self._handle_playback_completed)
        self._event_subscriber.subscribe(TransitionCompletedEvent, self._handle_transition_completed)
        self._event_subscriber.subscribe(VideoFirstFrameRenderedEvent, self._handle_video_first_frame_rendered)
        self._event_subscriber.subscribe(VideoPlaybackWarningEvent, self._handle_video_playback_warning)
        self._event_subscriber.subscribe(RendererConfigUpdatedEvent, self._handle_renderer_config_event)

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

    def stop(self) -> None:
        """Stop the playback engine and render loop."""
        self._logger.info("Stopping PlaybackEngine")
        self._is_running = False
        self._clear_pending_video_preparation()
        self._clear_pending_video_swap()
        if hasattr(self, '_active_video_media'):
            delattr(self, '_active_video_media')
        # We don't call renderer.stop() here because it might be called
        # from a signal handler which can cause issues with pi3d's
        # display destruction. The renderer will be stopped when the
        # run loop exits.
        self._change_state(State.IDLE)

    def _run_loop(self) -> None:
        """The main synchronous render loop."""
        while self._is_running:
            # 1. Process any pending events (non-blocking)
            # In a real implementation, we might poll the bus here if it\'s not
            # automatically dispatching to callbacks in this thread.
            # For now, we assume callbacks are handled.
            
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
                    self._renderer.stop()
                    self._renderer_started = False
                    if self._try_start_renderer():
                        self._prepare_playback_after_renderer_start()
                    continue

                self._handle_video_first_frame_timeout(current_time)
                if (
                    self._state == State.PLAYING
                    and current_time >= self._next_transition_time
                ):
                    self._trigger_next_media()
                    
                # Check if it\'s time to swap the background texture
                if current_time >= getattr(self, '_texture_swap_time', float('inf')) and getattr(self, '_pending_swap_media', None):
                    self._execute_texture_swap()
                    
                # 3. Render the frame
                if not self._renderer.render_frame():
                    self._logger.info("Renderer requested exit")
                    self._is_running = False
                    break
                    
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
        if self._state == State.PREPARING_VIDEO and event.command in (Command.NEXT, Command.PREV, Command.STOP):
            self._logger.info(f"Interrupting video preparation with command: {event.command}")
            self._clear_pending_video_preparation()
            self._clear_pending_video_swap()
            if self._video_player:
                self._video_player.stop()
            self._change_state(State.IDLE)

        if event.command == Command.NEXT:
            self._trigger_next_media()
        elif event.command == Command.PREV:
            self._trigger_prev_media()
        elif event.command == Command.PAUSE:
            self._change_state(State.IDLE)
            if self._video_player and self._state == State.PLAYING:
                self._video_player.pause()
        elif event.command == Command.PLAY:
            self._change_state(State.PLAYING)
            # Reset timer so it doesn't immediately transition if it was paused
            self._next_transition_time = time.time() + self._time_delay
            if self._video_player:
                self._video_player.resume()
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

    def _handle_state_event(self, event: StateEvent) -> None:
        """React to runtime configuration changes."""
        if event.state != State.CONFIG_CHANGED:
            return
        payload = event.payload if isinstance(event.payload, dict) else {}
        updated_sections = payload.get("updated_sections", [])
        if "model" not in updated_sections:
            return

        self._refresh_model_timing()
        if self._renderer_started:
            self._playlist_manager.build_playlist()
            self._playlist_ready = True
        if self._state == State.PLAYING and self._next_transition_time != float("inf"):
            self._next_transition_time = min(
                self._next_transition_time,
                time.time() + self._time_delay,
            )

    def _handle_renderer_config_event(self, event: RendererConfigUpdatedEvent) -> None:
        """Record renderer config updates; main loop performs renderer work."""
        if not isinstance(event, RendererConfigUpdatedEvent):
            return

        old_signature = self._renderer_asset_signature(self._renderer_config)
        new_signature = self._renderer_asset_signature(event.config)
        self._renderer_config = event.config
        if not self._renderer_started or old_signature != new_signature:
            self._renderer_retry_requested = True

    @staticmethod
    def _renderer_asset_signature(config: RendererConfig | None) -> tuple[Any, ...] | None:
        if config is None:
            return None
        return (
            config.display_x,
            config.display_y,
            config.display_w,
            config.display_h,
            config.shader_path,
            config.font_file,
            config.show_text_enabled,
            config.show_clock,
            config.mat_images,
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
        _, _, renderer_w, renderer_h = self._renderer.get_display_rect()
        configured_rect = self._configured_display_rect()
        if configured_rect is not None:
            return configured_rect[2], configured_rect[3]
        return renderer_w, renderer_h

    def _video_display_rect(self) -> tuple[int, int, int, int]:
        renderer_rect = self._renderer.get_display_rect()
        if self._configured_display_is_fullscreen():
            fullscreen_rect = (0, 0, 0, 0)
            if renderer_rect != fullscreen_rect:
                self._logger.info(
                    "Using fullscreen video display rect %s instead of renderer-reported %s.",
                    fullscreen_rect,
                    renderer_rect,
                )
            return fullscreen_rect

        configured_rect = self._configured_display_rect()
        if configured_rect is None:
            return renderer_rect
        if configured_rect != renderer_rect:
            self._logger.info(
                "Using configured video display rect %s instead of renderer-reported %s.",
                configured_rect,
                renderer_rect,
            )
        return configured_rect

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

        if self._config_repository:
            show_clock = self._config_repository.get_app_config_bool(
                "viewer.show_clock", self._config.get("show_clock", False)
            )
            clock_format = str(
                self._config_repository.get_app_config(
                    "viewer.clock_format", self._config.get("clock_format", "%H:%M")
                )
            )
            show_text = self._config_repository.get_app_config_bool(
                "viewer.show_text_enabled",
                self._text_overlay_enabled(self._config.get("show_text", False)),
            )
        else:
            show_clock = (
                str(self._config.get("show_clock", False)).lower()
                in ("true", "1", "t", "y", "yes")
                if isinstance(self._config.get("show_clock", False), str)
                else bool(self._config.get("show_clock", False))
            )
            clock_format = str(self._config.get("clock_format", "%H:%M"))
            show_text = self._text_overlay_enabled(
                self._config.get("show_text_enabled", self._config.get("show_text", False))
            )

        text_strings = tuple(self._generate_text_string(item) for item in display_item.items)
        return OverlayConfig(
            show_clock=show_clock,
            clock_format=clock_format,
            show_text=show_text,
            text_string=text_strings[display_item.primary_index] if text_strings else "",
            text_strings=text_strings if display_item.layout == DisplayLayout.PORTRAIT_PAIR else (),
        )

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
                if self._playlist_manager._current_index < len(self._playlist_manager._display_playlist):
                    slot_data = self._playlist_manager._display_playlist[self._playlist_manager._current_index]
                    display_item = self._playlist_manager._slot_to_display_item(slot_data)
                    self._event_publisher.publish(CurrentMediaChangedEvent(media_item=display_item))
            else:
                # Fallback to placeholder if playlist is empty
                placeholder = self._playlist_manager._get_no_images_placeholder()
                self._event_publisher.publish(CurrentMediaChangedEvent(media_item=DisplayItem.single(placeholder)))

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
        media_ids = [int(media_id) for media_id in raw_media_ids] if isinstance(raw_media_ids, list) else None

        delete_ids = self._playlist_manager.resolve_current_delete_ids(target, media_ids)
        if not delete_ids:
            message = "Delete request did not match the current display item."
            self._logger.warning(message)
            self._event_publisher.publish(
                SystemErrorEvent(message=message, component="PlaybackEngine")
            )
            return

        items_by_id = {
            int(item.id): item
            for item in current_display.items
            if item.id is not None
        }
            
        # Determine deleted directory
        if self._config_repository:
            deleted_dir_config = self._config_repository.get_app_config("model.deleted_pictures", self._config.get("deleted_pictures", "~/DeletedPictures"))
        else:
            deleted_dir_config = self._config.get("deleted_pictures", "~/DeletedPictures")
            
        deleted_dir = os.path.expanduser(deleted_dir_config)
        
        moved_ids: list[int] = []
        try:
            os.makedirs(deleted_dir, exist_ok=True)
            for media_id in delete_ids:
                media_item = items_by_id.get(media_id)
                if media_item is None:
                    self._logger.warning("Delete target is no longer in the current display item: %s", media_id)
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

    def _trigger_next_media(self) -> None:
        """Fetch the next media item and send a render command."""
        if not self._renderer_started and self._state == State.ERROR:
            self._renderer_retry_requested = True
            return

        self._clear_pending_video_preparation()
        self._clear_pending_video_swap()
        if hasattr(self, '_active_video_media'):
            delattr(self, '_active_video_media')
            
        display_item = self._as_display_item(self._playlist_manager.get_next())
        if display_item:
            media_item = display_item.primary
            self._logger.info(
                "Transitioning to next display item: %s",
                ", ".join(item.filepath for item in display_item.items),
            )
            self._change_state(State.TRANSITIONING)
            
            overlay_config = self._build_overlay_config(display_item)
            
            # Check if it's a video
            video_extensions = tuple(ext.lower() for ext in self._config.get("video_extensions", ['.mp4', '.mov', '.mkv', '.avi', '.webm']))
            is_video = self._is_video_media(media_item, video_extensions)
            
            if is_video and self._video_player:
                # 1. On-demand fallback for missing frames
                import os

                from picframe.core.utils.video_frame_extractor import VideoFrameExtractor
                base, _ = os.path.splitext(media_item.filepath)
                first_frame_path = base + ".1.frame"
                last_frame_path = base + ".2.frame"
                
                duration = getattr(media_item, 'duration', 0.0)
                if duration is None:
                    duration = 0.0
                display_w, display_h = self._video_frame_dimensions()
                
                first_img = None
                last_img = None
                
                if duration > 0 and display_w is not None and display_h is not None and display_w > 0 and display_h > 0:
                    try:
                        fit_display = False
                        if self._config_repository is not None:
                            fit_display = self._config_repository.get_app_config_bool("viewer.fit", self._config.get("fit", False))
                        else:
                            fit_display = self._config.get("fit", False)
                        extractor = VideoFrameExtractor(
                            media_item.filepath,
                            display_w,
                            display_h,
                            fit_display=fit_display,
                            cache_dir=self._cache_dir,
                        )
                        first_frame_path = extractor.get_frame_path("first")
                        last_frame_path = extractor.get_frame_path("last")
                        frames = extractor.get_first_and_last_frames(duration, display_w, display_h)
                        if frames:
                            first_img, last_img = frames
                    except Exception as e:
                        self._logger.error(f"Failed to extract frames for {media_item.filepath}: {e}")
                
                # 2. Send RenderCommand for the first frame
                if first_img is not None:
                    self._logger.debug(f"Sending first frame to renderer: {first_frame_path}")
                    self._renderer.execute(RenderCommand(image_path=first_frame_path, overlay=overlay_config, image_obj=first_img))
                    
                    # 3. Change state to PREPARING_VIDEO
                    self._change_state(State.PREPARING_VIDEO)
                    
                    # We need to wait for TransitionCompletedEvent before playing the video.
                    # For now, we'll store the pending media item.
                    self._pending_video_media = media_item
                    self._pending_last_img = last_img
                    self._pending_last_frame_path = last_frame_path
                    self._next_transition_time = float('inf')
                else:
                    self._logger.warning(
                        "Could not generate first frame for %s; playing video directly.",
                        media_item.filepath,
                    )
                    self._renderer.execute(RenderCommand(image_path="RESUME", overlay=overlay_config))
                    x, y, w, h = self._video_display_rect()
                    self._video_player.play(media_item, x, y, w, h)
                    self._next_transition_time = float('inf')
                    self._change_state(State.PLAYING)
            else:
                if self._video_player:
                    self._video_player.stop()
                if display_item.layout == DisplayLayout.PORTRAIT_PAIR:
                    render_cmd = self._pair_render_command(display_item, overlay_config)
                else:
                    render_cmd = RenderCommand(image_path=media_item.filepath, overlay=overlay_config)
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
        if self._state == State.PREPARING_VIDEO and hasattr(self, '_pending_video_media'):
            self._logger.info("First frame transition completed, starting video playback.")
            if self._video_player:
                x, y, w, h = self._video_display_rect()
                self._video_player.play(self._pending_video_media, x, y, w, h)
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
            or not hasattr(self, '_pending_video_media')
            or getattr(event, "warning_type", None) != "software_fallback"
        ):
            return

        current_deadline = getattr(self, '_video_first_frame_deadline', None)
        fallback_deadline = (
            time.time() + self._video_software_fallback_first_frame_timeout
        )
        self._video_first_frame_deadline = max(
            current_deadline or 0.0,
            fallback_deadline,
        )
        self._logger.info(
            "Extended GStreamer first-frame deadline for software decoder fallback: %s",
            getattr(event, "decoder", "unknown"),
        )

    def _handle_video_first_frame_timeout(self, current_time: float) -> None:
        """Avoid getting stuck if GStreamer does not report first-frame readiness."""
        deadline = getattr(self, '_video_first_frame_deadline', None)
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
        """Reveal video playback and prepare the last-frame sandwich swap."""
        if self._state == State.PREPARING_VIDEO and hasattr(self, '_pending_video_media'):
            self._logger.info("GStreamer first frame rendered, fading out pi3d.")
            media_item = self._pending_video_media
            last_img = getattr(self, '_pending_last_img', None)
            last_frame_path = getattr(self, '_pending_last_frame_path', None)
            self._active_video_media = media_item
            self._change_state(State.PLAYING)
            
            # Schedule the mid-playback texture swap on the main loop
            self._pending_swap_media = media_item
            self._pending_swap_last_img = last_img
            self._pending_swap_last_frame_path = last_frame_path
            self._texture_swap_time = time.time() + 1.0
            self._video_suspend_generation += 1
            self._clear_pending_video_preparation()

    def _execute_texture_swap(self) -> None:
        """Execute the background texture swap on the main thread."""
        import os

        from picframe.core.events.dto import RenderCommand
        
        media_item = getattr(self, '_pending_swap_media', None)
        active_media = getattr(self, '_active_video_media', None)

        if not media_item:
            self._clear_pending_video_swap()
            return

        if not self._same_media_item(media_item, active_media):
            self._logger.debug(
                "Ignoring stale video texture swap for %s; active video is %s.",
                getattr(media_item, "filepath", None),
                getattr(active_media, "filepath", None),
            )
            self._clear_pending_video_swap()
            return

        last_img = getattr(self, '_pending_swap_last_img', None)
        last_frame_path = getattr(self, '_pending_swap_last_frame_path', None)
        self._clear_pending_video_swap(invalidate_suspend=False)

        if last_frame_path is None:
            base, _ = os.path.splitext(media_item.filepath)
            last_frame_path = base + ".2.frame"
        
        if last_img is not None:
            self._logger.info(f"Swapping background texture to last frame: {last_frame_path}")
            self._renderer.execute(RenderCommand(image_path=last_frame_path, background_only=True, image_obj=last_img))
        else:
            self._logger.warning(f"Last frame not found for swap: {last_frame_path}")
            
        # Suspend pi3d rendering to save CPU while video plays
        # We need to give the renderer a chance to process the background_only command
        # before suspending it, otherwise the texture swap is never drawn.
        import threading
        suspend_generation = self._video_suspend_generation
        threading.Timer(
            0.5,
            lambda: self._suspend_renderer_if_video_active(suspend_generation),
        ).start()

    def _handle_playback_completed(self, event: Any) -> None:
        """Handle the completion of video playback."""
        self._logger.info("Video playback completed, scheduling transition to next media.")
        if self._state == State.PREPARING_VIDEO and hasattr(self, '_pending_video_media'):
            self._logger.warning("Video playback completed before first-frame handoff.")
            self._clear_pending_video_preparation()
            self._change_state(State.PLAYING)

        self._clear_pending_video_swap()
        if hasattr(self, '_active_video_media'):
            delattr(self, '_active_video_media')

        # Wake up the renderer from SUSPENDED state
        self._renderer.execute(RenderCommand(image_path="RESUME", overlay=None))
        
        # Explicitly stop the video player to destroy the GStreamer window.
        # This reveals the pi3d window underneath, which is currently displaying the last frame.
        if self._video_player:
            self._video_player.stop()
            
        # Instead of calling _trigger_next_media directly (which might be from a different thread),
        # we set the transition time to 0 so the main loop picks it up immediately.
        self._next_transition_time = 0.0

    def _trigger_prev_media(self) -> None:
        """Fetch the previous media item and send a render command."""
        self._clear_pending_video_preparation()
        self._clear_pending_video_swap()
        if hasattr(self, '_active_video_media'):
            delattr(self, '_active_video_media')
            
        display_item = self._as_display_item(self._playlist_manager.get_previous())
        if display_item:
            media_item = display_item.primary
            self._logger.info(
                "Transitioning to previous display item: %s",
                ", ".join(item.filepath for item in display_item.items),
            )
            self._change_state(State.TRANSITIONING)
            
            overlay_config = self._build_overlay_config(display_item)
            
            video_extensions = tuple(ext.lower() for ext in self._config.get("video_extensions", ['.mp4', '.mov', '.mkv', '.avi', '.webm']))
            is_video = self._is_video_media(media_item, video_extensions)
            
            if is_video and self._video_player:
                self._renderer.execute(RenderCommand(image_path="RESUME", overlay=overlay_config))
                self._video_player.play(media_item)
                self._next_transition_time = float('inf')
            else:
                if self._video_player:
                    self._video_player.stop()
                if display_item.layout == DisplayLayout.PORTRAIT_PAIR:
                    render_cmd = self._pair_render_command(display_item, overlay_config)
                else:
                    render_cmd = RenderCommand(image_path=media_item.filepath, overlay=overlay_config)
                try:
                    self._renderer.execute(render_cmd)
                    self._next_transition_time = time.time() + self._time_delay
                except MediaProcessingError as e:
                    self._handle_media_error(e)
            
            # Publish media changed event
            self._event_publisher.publish(CurrentMediaChangedEvent(media_item=display_item))
            
            self._change_state(State.PLAYING)
        else:
            self._logger.warning("No previous media available")

    def _clear_pending_video_preparation(self) -> None:
        """Clear cached first-frame handoff state for an unstarted video."""
        for attr in (
            '_pending_video_media',
            '_pending_last_img',
            '_pending_last_frame_path',
            '_video_first_frame_deadline',
        ):
            if hasattr(self, attr):
                delattr(self, attr)

    def _clear_pending_video_swap(self, *, invalidate_suspend: bool = True) -> None:
        """Clear delayed video last-frame swap state."""
        for attr in (
            '_pending_swap_media',
            '_pending_swap_last_img',
            '_pending_swap_last_frame_path',
        ):
            if hasattr(self, attr):
                delattr(self, attr)
        self._texture_swap_time = float('inf')
        if invalidate_suspend:
            self._video_suspend_generation += 1

    @staticmethod
    def _same_media_item(left: Any, right: Any) -> bool:
        """Return True when two media item references describe the same file."""
        if left is None or right is None:
            return False
        if left is right:
            return True
        left_id = getattr(left, "id", None)
        right_id = getattr(right, "id", None)
        if left_id is not None and right_id is not None and left_id == right_id:
            return True
        return getattr(left, "filepath", None) == getattr(right, "filepath", None)

    def _suspend_renderer_if_video_active(self, generation: int) -> None:
        """Suspend pi3d only if the video swap timer still belongs to the active video."""
        if generation != self._video_suspend_generation:
            return
        if self._state != State.PLAYING or not hasattr(self, '_active_video_media'):
            return

        from picframe.core.events.dto import RenderCommand

        self._renderer.execute(RenderCommand(image_path="SUSPEND", overlay=None))

    def _generate_text_string(self, media_item: Any) -> str:
        """Generate the text overlay string based on configuration and media metadata."""
        # If it's the fallback image, don't show any text
        if media_item.filepath.endswith("no_pictures.jpg"):
            return ""
            
        # Fetch the live configuration from the repository if available, otherwise use the initial config
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
        else:
            show_text_enabled = self._text_overlay_enabled(
                self._config.get("show_text_enabled", self._config.get("show_text", False))
            )
            show_text_config = self._text_overlay_format()
            show_text_fm = str(self._config.get("show_text_fm", "%b %d, %Y"))
            
        if not show_text_enabled or not self._text_overlay_enabled(show_text_config):
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
            import os
            parts.append(os.path.basename(os.path.dirname(media_item.filepath)))
            
        if "location" in show_text_config:
            location = getattr(media_item, "location", None)
            if not location and getattr(media_item, "latitude", None) is not None and getattr(media_item, "longitude", None) is not None:
                # Check if it's in the database cache first
                cached_location = self._playlist_manager._media_repo.get_location(media_item.latitude, media_item.longitude)
                if cached_location:
                    location = cached_location
                    media_item.location = location
                else:
                    # Enqueue for background processing
                    self._playlist_manager._media_repo.enqueue_location_lookup(media_item.latitude, media_item.longitude)
            
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
