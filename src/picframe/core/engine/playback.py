"""
Playback Engine for orchestrating media playback and rendering.
"""
import logging
import time
from typing import Any

from picframe.core.events.dto import (
    Command,
    CommandEvent,
    RenderCommand,
    State,
    StateEvent,
    CurrentMediaChangedEvent,
)
from picframe.core.events.interfaces import IEventPublisher, IEventSubscriber
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
    ) -> None:
        """
        Initialize the PlaybackEngine.
        
        Args:
            event_bus: The central event bus for publishing and subscribing.
            playlist_manager: Service for retrieving media items.
            renderer: The presentation layer component for drawing pixels.
            config: Application configuration.
        """
        self._logger = logging.getLogger(__name__)
        self._event_publisher = event_publisher
        self._event_subscriber = event_subscriber
        self._playlist_manager = playlist_manager
        self._renderer = renderer
        self._config = config
        
        self._state = State.IDLE
        self._is_running = False
        self._time_delay = float(config.get("time_delay", 200.0))
        self._next_transition_time = 0.0
        
        # Subscribe to commands
        self._event_subscriber.subscribe(CommandEvent, self._handle_command)

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
        # We don't call renderer.stop() here because it might be called
        # from a signal handler which can cause issues with pi3d's
        # display destruction. The renderer will be stopped when the
        # run loop exits.
        self._change_state(State.IDLE)

    def _run_loop(self) -> None:
        """The main synchronous render loop."""
        while self._is_running:
            # 1. Process any pending events (non-blocking)
            # In a real implementation, we might poll the bus here if it's not
            # automatically dispatching to callbacks in this thread.
            # For now, we assume callbacks are handled.
            
            # 2. Check if it's time for the next slide
            current_time = time.time()
            if (
                self._state == State.PLAYING
                and current_time >= self._next_transition_time
            ):
                self._trigger_next_media()
                
            # 3. Render the frame
            if not self._renderer.render_frame():
                self._logger.info("Renderer requested exit")
                self._is_running = False
                break
                
            # Small sleep to prevent 100% CPU usage if renderer doesn't block
            time.sleep(0.01)
            
        self._logger.info("Exiting render loop, stopping renderer")
        self._renderer.stop()

    def _handle_command(self, event: CommandEvent) -> None:
        """Handle incoming commands from the Event Bus."""
        self._logger.debug(f"Received command: {event.command}")
        
        if event.command == Command.NEXT:
            self._trigger_next_media()
        elif event.command == Command.PREV:
            self._trigger_prev_media()
        elif event.command == Command.PAUSE:
            self._change_state(State.IDLE)
        elif event.command == Command.PLAY:
            self._change_state(State.PLAYING)
            # Reset timer so it doesn't immediately transition if it was paused
            self._next_transition_time = time.time() + self._time_delay
        elif event.command == Command.STOP:
            self.stop()
        elif event.command == Command.DELETE:
            self._handle_delete_command()
        elif event.command == Command.PURGE_FILES:
            self._handle_purge_command()
        elif event.command == Command.REQUEST_STATE:
            self._handle_request_state()

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
        base_dir = os.path.dirname(filepath)
        deleted_dir = os.path.join(base_dir, "deleted_pictures")
        
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
            overlay_config = OverlayConfig(
                show_clock=bool(self._config.get("show_clock", False)),
                clock_format=str(self._config.get("clock_format", "%H:%M")),
                show_text=bool(self._config.get("show_text", False)),
                text_string=text_string
            )
            
            render_cmd = RenderCommand(image_path=media_item.filepath, overlay=overlay_config)
            self._renderer.execute(render_cmd)
            
            # Publish media changed event
            self._event_publisher.publish(CurrentMediaChangedEvent(media_item=media_item))
            
            # Update timer
            self._next_transition_time = time.time() + self._time_delay
            
            self._change_state(State.PLAYING)
        else:
            self._logger.warning("No media available to play")

    def _trigger_prev_media(self) -> None:
        """Fetch the previous media item and send a render command."""
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
            overlay_config = OverlayConfig(
                show_clock=bool(self._config.get("show_clock", False)),
                clock_format=str(self._config.get("clock_format", "%H:%M")),
                show_text=bool(self._config.get("show_text", False)),
                text_string=text_string
            )
            
            render_cmd = RenderCommand(image_path=media_item.filepath, overlay=overlay_config)
            self._renderer.execute(render_cmd)
            
            # Publish media changed event
            self._event_publisher.publish(CurrentMediaChangedEvent(media_item=media_item))
            
            # Update timer
            self._next_transition_time = time.time() + self._time_delay
            
            self._change_state(State.PLAYING)
        else:
            self._logger.warning("No previous media available")

    def _generate_text_string(self, media_item: Any) -> str:
        """Generate the text overlay string based on configuration and media metadata."""
        # If it's the fallback image, don't show any text
        if media_item.filepath.endswith("no_pictures.jpg"):
            return ""
            
        # In a full implementation, we would fetch this from the config repository.
        # For now, we'll use the default config or what was passed in.
        show_text_config = str(self._config.get("show_text", "")).lower()
        if not show_text_config or show_text_config == "false" or show_text_config == "off":
            return ""
            
        parts = []
        
        if "title" in show_text_config and media_item.title:
            parts.append(media_item.title)
            
        if "caption" in show_text_config and media_item.caption:
            parts.append(media_item.caption)
            
        if "name" in show_text_config and media_item.filename:
            parts.append(media_item.filename)
            
        if "date" in show_text_config and media_item.exif_datetime:
            import datetime
            try:
                dt = datetime.datetime.fromtimestamp(media_item.exif_datetime)
                parts.append(dt.strftime("%Y-%m-%d %H:%M"))
            except Exception:
                pass
                
        if "folder" in show_text_config and media_item.filepath:
            import os
            parts.append(os.path.basename(os.path.dirname(media_item.filepath)))
            
        if "location" in show_text_config and media_item.location:
            parts.append(media_item.location)
            
        return " - ".join(parts)

    def _change_state(self, new_state: State) -> None:
        """Update internal state and publish a StateEvent."""
        if self._state != new_state:
            self._logger.debug(f"State changed: {self._state} -> {new_state}")
            self._state = new_state
            self._event_publisher.publish(StateEvent(state=new_state))
