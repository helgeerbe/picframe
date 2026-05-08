"""
Playback Engine for orchestrating media playback and rendering.
"""
import logging
import time
from typing import Any

from picframe.core.events.dto import (
    Command,
    CommandEvent,
    CurrentMediaChangedEvent,
    RenderCommand,
    State,
    StateEvent,
    SystemErrorEvent,
)
from picframe.core.events.interfaces import IEventPublisher, IEventSubscriber
from picframe.core.exceptions import MediaProcessingError
from picframe.core.renderers.interfaces import IRenderer
from picframe.core.services.playlist import PlaylistManager


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
        
        self._state = State.IDLE
        self._is_running = False
        self._time_delay = float(config.get("time_delay", 200.0))
        self._next_transition_time = 0.0
        
        # Circuit breaker state
        self._consecutive_errors = 0
        self._max_consecutive_errors = 5
        
        # Subscribe to commands
        self._event_subscriber.subscribe(CommandEvent, self._handle_command)
        
        # Subscribe to video playback completion
        from picframe.core.events.dto import (
            PlaybackCompletedEvent,
            TransitionCompletedEvent,
            VideoFirstFrameRenderedEvent,
        )
        self._event_subscriber.subscribe(PlaybackCompletedEvent, self._handle_playback_completed)
        self._event_subscriber.subscribe(TransitionCompletedEvent, self._handle_transition_completed)
        self._event_subscriber.subscribe(VideoFirstFrameRenderedEvent, self._handle_video_first_frame_rendered)

    def start(self) -> None:
        """Start the playback engine and render loop."""
        self._logger.info("Starting PlaybackEngine")
        self._is_running = True
        self._renderer.start()
        
        # Build the initial playlist before starting the loop
        self._playlist_manager.build_playlist()
        
        # Initial state transition
        self._change_state(State.PLAYING)
        
        # Force immediate transition for the first image
        self._next_transition_time = 0.0
        
        # Main render loop
        self._run_loop()

    def stop(self) -> None:
        """Stop the playback engine and render loop."""
        self._logger.info("Stopping PlaybackEngine")
        self._is_running = False
        if hasattr(self, '_pending_video_media'):
            del self._pending_video_media
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
        
        # If we are preparing a video, we need to handle interruptions gracefully
        if self._state == State.PREPARING_VIDEO and event.command in (Command.NEXT, Command.PREV, Command.STOP):
            self._logger.info(f"Interrupting video preparation with command: {event.command}")
            if hasattr(self, '_pending_video_media'):
                delattr(self, '_pending_video_media')
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
            self._handle_delete_command()
        elif event.command == Command.PURGE_FILES:
            self._handle_purge_command()
        elif event.command == Command.REQUEST_STATE:
            self._handle_request_state()
        elif event.command == Command.SET_VOL:
            if self._video_player and event.payload is not None:
                self._video_player.set_volume(float(event.payload))

    def _handle_request_state(self) -> None:
        """Handle a request to broadcast the current state and media."""
        self._event_publisher.publish(StateEvent(state=self._state))
        current_media = self._playlist_manager.get_current()
        if current_media:
            self._event_publisher.publish(CurrentMediaChangedEvent(media_item=current_media))
        else:
            # If there's no current media (e.g., on startup before the first transition),
            # try to get the next one to populate the initial state.
            # We don't trigger a full transition here, just fetch the data.
            if self._playlist_manager._playlist:
                # Peek at the first item without advancing the index
                if self._playlist_manager._current_index < len(self._playlist_manager._playlist):
                    item_data = self._playlist_manager._playlist[self._playlist_manager._current_index]
                    media_item = self._playlist_manager._dict_to_media_item(item_data)
                    self._event_publisher.publish(CurrentMediaChangedEvent(media_item=media_item))
            else:
                # Fallback to placeholder if playlist is empty
                placeholder = self._playlist_manager._get_no_images_placeholder()
                self._event_publisher.publish(CurrentMediaChangedEvent(media_item=placeholder))

    def _handle_delete_command(self) -> None:
        """Handle the DELETE command by moving the current file and advancing."""
        import os
        import shutil
        
        current_media = self._playlist_manager.get_current()
        if not current_media or current_media.id == 0:
            self._logger.warning("No active media to delete.")
            return
            
        filepath = current_media.filepath
        if not os.path.exists(filepath):
            self._logger.warning(f"File to delete not found: {filepath}")
            return
            
        # Determine deleted directory
        if self._config_repository:
            deleted_dir_config = self._config_repository.get_app_config("model.deleted_pictures", self._config.get("deleted_pictures", "~/DeletedPictures"))
        else:
            deleted_dir_config = self._config.get("deleted_pictures", "~/DeletedPictures")
            
        deleted_dir = os.path.expanduser(deleted_dir_config)
        
        try:
            os.makedirs(deleted_dir, exist_ok=True)
            filename = os.path.basename(filepath)
            dest_path = os.path.join(deleted_dir, filename)
            
            # Move the file
            shutil.move(filepath, dest_path)
            self._logger.info(f"Moved deleted file to: {dest_path}")
            
            # Mark as deleted in repository
            self._playlist_manager.delete_current()
            
            # Immediately transition to next media
            self._trigger_next_media()
            
        except Exception as e:
            self._logger.error(f"Failed to delete file {filepath}: {e}")

    def _handle_purge_command(self) -> None:
        """Handle the PURGE_FILES command by cleaning up the database."""
        self._logger.info("Executing PURGE_FILES command.")
        purged_count = self._playlist_manager.purge_missing_files()
        self._logger.info(f"Purged {purged_count} missing files from database.")
        
        # Rebuild playlist to ensure we don't try to play purged items
        self._playlist_manager.build_playlist()

    def _trigger_next_media(self) -> None:
        """Fetch the next media item and send a render command."""
        if hasattr(self, '_pending_video_media'):
            delattr(self, '_pending_video_media')
            
        media_item = self._playlist_manager.get_next()
        if media_item:
            self._logger.info(
                f"Transitioning to next media: {media_item.filepath}"
            )
            self._change_state(State.TRANSITIONING)
            
            # Generate dynamic text string based on configuration
            text_string = self._generate_text_string(media_item)
            
            # Send render command
            # We pass the dynamically generated text string in the overlay config.
            # The renderer still manages the clock and visibility toggles via IConfigRepository.
            from picframe.core.events.dto import OverlayConfig
            
            # Fetch live config if available
            if self._config_repository:
                show_clock = self._config_repository.get_app_config_bool("viewer.show_clock", self._config.get("show_clock", False))
                clock_format = str(self._config_repository.get_app_config("viewer.clock_format", self._config.get("clock_format", "%H:%M")))
                show_text = bool(self._config_repository.get_app_config("viewer.show_text", self._config.get("show_text", False)))
            else:
                show_clock = str(self._config.get("show_clock", False)).lower() in ("true", "1", "t", "y", "yes") if isinstance(self._config.get("show_clock", False), str) else bool(self._config.get("show_clock", False))
                clock_format = str(self._config.get("clock_format", "%H:%M"))
                show_text = bool(self._config.get("show_text", False))
                
            overlay_config = OverlayConfig(
                show_clock=show_clock,
                clock_format=clock_format,
                show_text=show_text,
                text_string=text_string
            )
            
            # Check if it's a video
            video_extensions = tuple(ext.lower() for ext in self._config.get("video_extensions", ['.mp4', '.mov', '.mkv', '.avi', '.webm']))
            is_video = media_item.filepath.lower().endswith(video_extensions)
            
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
                _, _, display_w, display_h = self._renderer.get_display_rect()
                
                first_img = None
                last_img = None
                
                if duration > 0 and display_w is not None and display_h is not None and display_w > 0 and display_h > 0:
                    try:
                        fit_display = False
                        if self._config_repository is not None:
                            fit_display = self._config_repository.get_app_config_bool("viewer.fit", self._config.get("fit", False))
                        else:
                            fit_display = self._config.get("fit", False)
                        extractor = VideoFrameExtractor(media_item.filepath, display_w, display_h, fit_display=fit_display)
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
                    self._next_transition_time = float('inf')
                else:
                    self._logger.warning(f"Could not generate first frame for {media_item.filepath}, skipping video.")
                    # Skip the video and immediately trigger the next media item
                    # To avoid recursion in tests, we just return here if we're already in a recursive call
                    import inspect
                    if len([f for f in inspect.stack() if f.function == '_trigger_next_media']) > 5:
                        return
                    self._trigger_next_media()
                    return
            else:
                if self._video_player:
                    self._video_player.stop()
                render_cmd = RenderCommand(image_path=media_item.filepath, overlay=overlay_config)
                try:
                    self._renderer.execute(render_cmd)
                    # Update timer for images
                    self._next_transition_time = time.time() + self._time_delay
                    self._change_state(State.PLAYING)
                except MediaProcessingError as e:
                    self._handle_media_error(e)
            
            # Publish media changed event
            self._event_publisher.publish(CurrentMediaChangedEvent(media_item=media_item))
        else:
            self._logger.warning("No media available to play")

    def _handle_transition_completed(self, event: Any) -> None:
        """Handle the completion of a visual transition."""
        if self._state == State.PREPARING_VIDEO and hasattr(self, '_pending_video_media'):
            self._logger.info("First frame transition completed, starting video playback.")
            if self._video_player:
                x, y, w, h = self._renderer.get_display_rect()
                self._video_player.play(self._pending_video_media, x, y, w, h)
            # We don't change state to PLAYING yet. We wait for VideoFirstFrameRenderedEvent.
            # This ensures pi3d stays opaque until GStreamer is actually rendering.
        elif self._state == State.TRANSITIONING:
            self._change_state(State.PLAYING)

    def _handle_video_first_frame_rendered(self, event: Any) -> None:
        """Handle the event indicating GStreamer has rendered its first frame."""
        if self._state == State.PREPARING_VIDEO and hasattr(self, '_pending_video_media'):
            self._logger.info("GStreamer first frame rendered, fading out pi3d.")
            self._change_state(State.PLAYING)
            
            # Schedule the mid-playback texture swap on the main loop
            self._pending_swap_media = self._pending_video_media
            self._texture_swap_time = time.time() + 1.0
            delattr(self, '_pending_video_media')

    def _execute_texture_swap(self) -> None:
        """Execute the background texture swap on the main thread."""
        import os

        from picframe.core.events.dto import RenderCommand
        
        media_item = getattr(self, '_pending_swap_media', None)
        last_img = getattr(self, '_pending_last_img', None)
        
        if hasattr(self, '_pending_swap_media'):
            delattr(self, '_pending_swap_media')
        if hasattr(self, '_pending_last_img'):
            delattr(self, '_pending_last_img')
            
        self._texture_swap_time = float('inf')
        
        if not media_item:
            return
            
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
        threading.Timer(0.5, lambda: self._renderer.execute(RenderCommand(image_path="SUSPEND", overlay=None))).start()

    def _handle_playback_completed(self, event: Any) -> None:
        """Handle the completion of video playback."""
        self._logger.info("Video playback completed, scheduling transition to next media.")
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
        if hasattr(self, '_pending_video_media'):
            delattr(self, '_pending_video_media')
            
        media_item = self._playlist_manager.get_previous()
        if media_item:
            self._logger.info(
                f"Transitioning to previous media: {media_item.filepath}"
            )
            self._change_state(State.TRANSITIONING)
            
            # Generate dynamic text string based on configuration
            text_string = self._generate_text_string(media_item)
            
            # Send render command
            from picframe.core.events.dto import OverlayConfig
            
            # Fetch live config if available
            if self._config_repository:
                show_clock = self._config_repository.get_app_config_bool("viewer.show_clock", self._config.get("show_clock", False))
                clock_format = str(self._config_repository.get_app_config("viewer.clock_format", self._config.get("clock_format", "%H:%M")))
                show_text = bool(self._config_repository.get_app_config("viewer.show_text", self._config.get("show_text", False)))
            else:
                show_clock = str(self._config.get("show_clock", False)).lower() in ("true", "1", "t", "y", "yes") if isinstance(self._config.get("show_clock", False), str) else bool(self._config.get("show_clock", False))
                clock_format = str(self._config.get("clock_format", "%H:%M"))
                show_text = bool(self._config.get("show_text", False))
                
            overlay_config = OverlayConfig(
                show_clock=show_clock,
                clock_format=clock_format,
                show_text=show_text,
                text_string=text_string
            )
            
            video_extensions = tuple(ext.lower() for ext in self._config.get("video_extensions", ['.mp4', '.mov', '.mkv', '.avi', '.webm']))
            is_video = media_item.filepath.lower().endswith(video_extensions)
            
            if is_video and self._video_player:
                self._renderer.execute(RenderCommand(image_path="RESUME", overlay=overlay_config))
                self._video_player.play(media_item)
                self._next_transition_time = float('inf')
            else:
                if self._video_player:
                    self._video_player.stop()
                render_cmd = RenderCommand(image_path=media_item.filepath, overlay=overlay_config)
                try:
                    self._renderer.execute(render_cmd)
                    self._next_transition_time = time.time() + self._time_delay
                except MediaProcessingError as e:
                    self._handle_media_error(e)
            
            # Publish media changed event
            self._event_publisher.publish(CurrentMediaChangedEvent(media_item=media_item))
            
            self._change_state(State.PLAYING)
        else:
            self._logger.warning("No previous media available")

    def _generate_text_string(self, media_item: Any) -> str:
        """Generate the text overlay string based on configuration and media metadata."""
        # If it's the fallback image, don't show any text
        if media_item.filepath.endswith("no_pictures.jpg"):
            return ""
            
        # Fetch the live configuration from the repository if available, otherwise use the initial config
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

    def _change_state(self, new_state: State) -> None:
        """Update internal state and publish a StateEvent."""
        if self._state != new_state:
            self._logger.debug(f"State changed: {self._state} -> {new_state}")
            self._state = new_state
            self._event_publisher.publish(StateEvent(state=new_state))
